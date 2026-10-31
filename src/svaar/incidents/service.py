"""Deterministic incident grouping and organization-scoped timelines.

A failed workflow run opens an incident keyed by a fingerprint of repository,
workflow and branch. Every later observation with the same fingerprint joins the
active incident, so its timeline shows the failure, reruns and any later success.
Nothing here infers recovery, claims or causes; it only orders recorded facts.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from svaar.identity.service import get_principal
from svaar.incidents.models import (
    ACTIVE_STATES,
    Incident,
    IncidentEvent,
    IncidentState,
    ObservedEvent,
)

# Conclusions that open or extend an incident. Cancelled and skipped runs are not failures.
FAILURE_CONCLUSIONS = frozenset({"failure", "timed_out", "startup_failure"})


class IncidentNotFoundError(Exception):
    """No incident with that ID exists in the caller's organization."""


@dataclass(frozen=True)
class GroupingResult:
    """Incident an observation joined, and whether this observation opened it."""

    incident: Incident
    opened: bool


@dataclass(frozen=True)
class TimelineEntry:
    """One recorded fact in occurrence order, with its source."""

    occurred_at: datetime
    source: str
    kind: str
    run_id: int | None
    run_attempt: int | None
    status: str | None
    conclusion: str | None


def fingerprint(org_id: uuid.UUID, repository_id: int, data: dict) -> str:
    """Hash the stable identity of a workflow on a branch, never run-specific values."""
    parts = [
        str(org_id),
        str(repository_id),
        str(data.get("workflow_id") or ""),
        data.get("head_branch") or "",
    ]
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def group_observation(
    session: Session,
    event: ObservedEvent,
    *,
    owner_principal_id: uuid.UUID | None = None,
    failure_key: str | None = None,
) -> GroupingResult | None:
    """Attach a newly recorded workflow observation to an incident, opening one on failure.

    Runs inside the ingest transaction. A transaction-scoped advisory lock on the
    organization and fingerprint serializes concurrent deliveries for one workflow,
    and a partial unique index backs the one-active-incident rule.
    """
    if event.source != "github" or not event.kind.startswith("workflow_run."):
        return None
    key = failure_key or fingerprint(event.org_id, event.repository_id, event.data)
    lock = int.from_bytes(
        hashlib.sha256(f"incident:{key}".encode()).digest()[:8], "big", signed=True
    )
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})

    failed = event.data.get("conclusion") in FAILURE_CONCLUSIONS
    incident = session.scalars(
        select(Incident)
        .where(
            Incident.org_id == event.org_id,
            Incident.fingerprint == key,
            Incident.state.in_(ACTIVE_STATES),
        )
        .with_for_update()
    ).one_or_none()

    opened = False
    if incident is None:
        if not failed:
            return None
        incident = Incident(
            org_id=event.org_id,
            repository_id=event.repository_id,
            owner_principal_id=(
                owner_principal_id
                if owner_principal_id is not None
                and get_principal(session, event.org_id, owner_principal_id) is not None
                else None
            ),
            fingerprint=key,
            workflow_id=event.data.get("workflow_id"),
            workflow_name=event.data.get("workflow_name"),
            head_branch=event.data.get("head_branch"),
            state=IncidentState.OPEN.value,
            failure_count=1,
            opened_at=event.occurred_at,
            last_failure_at=event.occurred_at,
        )
        session.add(incident)
        session.flush()
        opened = True
    elif failed:
        incident.failure_count += 1
        incident.last_failure_at = max(incident.last_failure_at, event.occurred_at)

    session.add(IncidentEvent(incident_id=incident.id, event_id=event.id))
    session.flush()
    return GroupingResult(incident=incident, opened=opened)


def get_incident(session: Session, org_id: uuid.UUID, incident_id: uuid.UUID) -> Incident:
    """Return an incident only when it belongs to the organization."""
    incident = session.scalars(
        select(Incident).where(Incident.id == incident_id, Incident.org_id == org_id)
    ).one_or_none()
    if incident is None:
        raise IncidentNotFoundError("Incident not found")
    return incident


def list_incidents(
    session: Session, org_id: uuid.UUID, *, active_only: bool = True, limit: int = 10
) -> list[Incident]:
    """Return the organization's incidents, most recently failing first."""
    query = select(Incident).where(Incident.org_id == org_id)
    if active_only:
        query = query.where(Incident.state.in_(ACTIVE_STATES))
    return list(
        session.scalars(query.order_by(Incident.last_failure_at.desc(), Incident.id).limit(limit))
    )


def latest_active_incident(session: Session, org_id: uuid.UUID) -> Incident | None:
    """Return the organization's most recently failing active incident."""
    incidents = list_incidents(session, org_id, active_only=True, limit=1)
    return incidents[0] if incidents else None


def timeline(session: Session, org_id: uuid.UUID, incident_id: uuid.UUID) -> list[TimelineEntry]:
    """Return the incident's recorded facts in occurrence order.

    Ties on occurrence time fall back to arrival order, then ID, so the order is
    stable. Arrival order never rewrites a source's occurrence timestamp.
    """
    get_incident(session, org_id, incident_id)
    rows = session.scalars(
        select(ObservedEvent)
        .join(IncidentEvent, IncidentEvent.event_id == ObservedEvent.id)
        .where(IncidentEvent.incident_id == incident_id, ObservedEvent.org_id == org_id)
        .order_by(ObservedEvent.occurred_at, ObservedEvent.received_at, ObservedEvent.id)
    )
    return [
        TimelineEntry(
            occurred_at=row.occurred_at,
            source=row.source,
            kind=row.kind,
            run_id=row.data.get("run_id"),
            run_attempt=row.data.get("run_attempt"),
            status=row.data.get("status"),
            conclusion=row.data.get("conclusion"),
        )
        for row in rows
    ]


def acknowledge(
    session: Session, org_id: uuid.UUID, incident_id: uuid.UUID, principal_id: uuid.UUID
) -> tuple[Incident, bool]:
    """Acknowledge an open incident; return it and whether this call changed its state."""
    changed = session.execute(
        update(Incident)
        .where(
            Incident.id == incident_id,
            Incident.org_id == org_id,
            Incident.state == IncidentState.OPEN.value,
        )
        .values(
            state=IncidentState.ACKNOWLEDGED.value,
            acknowledged_at=func.now(),
            acknowledged_by=principal_id,
        )
        .returning(Incident.id)
    ).one_or_none()
    incident = get_incident(session, org_id, incident_id)
    session.refresh(incident)
    return incident, changed is not None
