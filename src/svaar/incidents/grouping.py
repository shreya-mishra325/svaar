"""Log-aware incident membership without rewriting any observed source facts."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from svaar.incidents.fingerprints import ALGORITHM
from svaar.incidents.models import (
    ACTIVE_STATES,
    Incident,
    IncidentEvent,
    ObservedEvent,
    WorkflowLogSignature,
)
from svaar.incidents.service import FAILURE_CONCLUSIONS, GroupingResult, group_observation


def group_enriched_observation(
    session: Session,
    event: ObservedEvent,
    *,
    owner_principal_id: uuid.UUID | None,
    installation_id: int,
) -> GroupingResult | None:
    """Use verified attempt digest for failures; ambiguous success never picks a cause."""
    failed = event.data.get("conclusion") in FAILURE_CONCLUSIONS
    key = None
    if failed:
        signature = session.scalar(
            select(WorkflowLogSignature).where(
                WorkflowLogSignature.org_id == event.org_id,
                WorkflowLogSignature.repository_id == event.repository_id,
                WorkflowLogSignature.installation_id == installation_id,
                WorkflowLogSignature.run_id == event.data.get("run_id"),
                WorkflowLogSignature.run_attempt == event.data.get("run_attempt"),
                WorkflowLogSignature.head_sha == event.data.get("head_sha"),
                WorkflowLogSignature.workflow_id == event.data.get("workflow_id"),
                WorkflowLogSignature.head_branch == event.data.get("head_branch"),
                WorkflowLogSignature.algorithm == ALGORITHM,
            )
        )
        if signature is not None:
            key = signature.fingerprint
    else:
        related = session.scalar(
            select(Incident)
            .join(IncidentEvent, IncidentEvent.incident_id == Incident.id)
            .join(ObservedEvent, ObservedEvent.id == IncidentEvent.event_id)
            .where(
                Incident.org_id == event.org_id,
                Incident.repository_id == event.repository_id,
                Incident.state.in_(ACTIVE_STATES),
                ObservedEvent.data["run_id"].astext == str(event.data.get("run_id")),
            )
            .order_by(ObservedEvent.occurred_at.desc(), ObservedEvent.id)
            .limit(1)
        )
        if related is None:
            candidates = list(
                session.scalars(
                    select(Incident)
                    .where(
                        Incident.org_id == event.org_id,
                        Incident.repository_id == event.repository_id,
                        Incident.workflow_id == event.data.get("workflow_id"),
                        Incident.head_branch == event.data.get("head_branch"),
                        Incident.state.in_(ACTIVE_STATES),
                    )
                    .limit(2)
                )
            )
            related = candidates[0] if len(candidates) == 1 else None
        if related is None:
            return None
        key = related.fingerprint
    grouped = group_observation(
        session, event, owner_principal_id=owner_principal_id, failure_key=key
    )
    if grouped is not None and failed:
        # Earlier requested/in-progress facts for this exact attempt may have
        # arrived before the failure. Add only unlinked facts; never move links.
        earlier = session.scalars(
            select(ObservedEvent).where(
                ObservedEvent.org_id == event.org_id,
                ObservedEvent.repository_id == event.repository_id,
                ObservedEvent.source == "github",
                ObservedEvent.kind.in_(("workflow_run.requested", "workflow_run.in_progress")),
                ObservedEvent.data["run_id"].astext == str(event.data.get("run_id")),
                ObservedEvent.data["run_attempt"].astext == str(event.data.get("run_attempt")),
                ~select(IncidentEvent.event_id)
                .where(IncidentEvent.event_id == ObservedEvent.id)
                .exists(),
            )
        )
        for previous in earlier:
            session.add(IncidentEvent(incident_id=grouped.incident.id, event_id=previous.id))
        session.flush()
    return grouped
