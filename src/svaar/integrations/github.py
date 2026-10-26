"""Validate documented workflow_run payloads and atomically persist scoped observations."""

import hashlib
import json
import logging
import uuid
from datetime import UTC
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from svaar.agent.notifications import enqueue_private_notification
from svaar.incidents.alerts import opened_alerts
from svaar.incidents.models import Incident, ObservedEvent
from svaar.incidents.service import group_observation
from svaar.integrations.models import RepoMapping, WebhookDelivery

logger = logging.getLogger(__name__)


class GithubPayloadError(Exception):
    """Malformed authenticated input, without exposing payload details."""


class GithubJsonError(GithubPayloadError):
    """Authenticated body is not a valid unambiguous JSON object."""


class DeliveryConflictError(Exception):
    """A delivery ID or business event key was reused with different contents."""


class _Wire(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class _Identifier(_Wire):
    id: int = Field(gt=0, le=9223372036854775807, strict=True)


class _Run(_Wire):
    id: int = Field(gt=0, le=9223372036854775807, strict=True)
    run_attempt: int = Field(gt=0, le=2147483647, strict=True)
    head_sha: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    status: str = Field(min_length=1, max_length=32)
    conclusion: str | None
    updated_at: AwareDatetime
    # Optional so minimal payloads stay valid; they make the incident fingerprint precise.
    workflow_id: int | None = Field(default=None, gt=0, le=9223372036854775807, strict=True)
    name: str | None = Field(default=None, max_length=200)
    head_branch: str | None = Field(default=None, max_length=255)


class _Workflow(_Wire):
    action: Literal["requested", "in_progress", "completed"]
    repository: _Identifier
    installation: _Identifier
    workflow_run: _Run


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("Non-JSON numeric value")


def _normalize(event_type: str, raw: bytes) -> tuple[_Workflow | None, dict | None, str | None]:
    try:
        body = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_invalid_constant)
        if not isinstance(body, dict):
            raise ValueError("Object required")
    except (ValueError, TypeError, RecursionError):
        raise GithubJsonError("Invalid webhook JSON") from None
    if event_type != "workflow_run":
        return None, None, None
    try:
        event = _Workflow.model_validate(body)
        run = event.workflow_run
        if (
            (event.action == "completed" and (run.status != "completed" or run.conclusion is None))
            or (event.action == "in_progress" and run.status != "in_progress")
            or (
                event.action == "requested"
                and run.status not in {"queued", "requested", "pending", "waiting"}
            )
            or (event.action != "completed" and run.conclusion is not None)
        ):
            raise ValueError("Inconsistent workflow state")
        if run.conclusion is not None and run.conclusion not in {
            "success",
            "failure",
            "neutral",
            "cancelled",
            "skipped",
            "timed_out",
            "action_required",
            "stale",
            "startup_failure",
        }:
            raise ValueError("Unknown conclusion")
        occurred = run.updated_at.astimezone(UTC).isoformat()
        data = {
            "run_id": run.id,
            "run_attempt": run.run_attempt,
            "head_sha": run.head_sha,
            "status": run.status,
            "conclusion": run.conclusion,
            "workflow_id": run.workflow_id,
            "workflow_name": run.name,
            "head_branch": run.head_branch,
        }
        key = (
            f"workflow_run:{event.repository.id}:{run.id}:"
            f"{run.run_attempt}:{event.action}:{occurred}"
        )
        return event, data, key
    except (ValueError, TypeError, ValidationError, RecursionError):
        raise GithubPayloadError("Invalid webhook payload") from None


def _queue_opened_alerts(session: Session, incident: Incident) -> None:
    """Queue chat alerts with the incident, atomically; never send or rerun anything."""
    queued = sum(
        enqueue_private_notification(
            session,
            org_id=incident.org_id,
            principal_id=alert.principal_id,
            key=alert.key,
            body=alert.body,
        )
        for alert in opened_alerts(session, incident)
    )
    logger.info("incident_alerts_queued count=%d", queued)


def ingest_delivery(
    sessions: sessionmaker[Session],
    delivery_id: uuid.UUID,
    event_type: str,
    raw: bytes,
) -> str:
    """Commit dedupe and observations together; no tools, model or provider requests.

    Delivery ID conflicts are refused. A second ID for the same normalized run
    transition points to the same observation instead of creating another effect.
    Unsupported event types and unmapped installations are recorded as ignored.
    """
    event, data, key = _normalize(event_type, raw)
    digest = hashlib.sha256(raw).hexdigest()
    locks = {"github-delivery:" + str(delivery_id)}
    if key is not None:
        locks.add("github-event:" + key)
    with sessions.begin() as session:
        for number in sorted(
            int.from_bytes(hashlib.sha256(k.encode()).digest()[:8], "big", signed=True)
            for k in locks
        ):
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": number})
        previous = session.get(WebhookDelivery, delivery_id)
        if previous is not None:
            if previous.payload_hash != digest or previous.event_type != event_type:
                raise DeliveryConflictError("Delivery ID conflict")
            if previous.reason == "unmapped_repository":
                return "unmapped"
            if previous.reason == "unsupported_event":
                return "ignored"
            return "duplicate"
        receipt = WebhookDelivery(
            id=delivery_id,
            payload_hash=digest,
            event_type=event_type,
            state="ignored",
            reason="unsupported_event",
        )
        if event is None:
            session.add(receipt)
            return "ignored"
        mapping = session.get(RepoMapping, event.repository.id)
        if mapping is None or mapping.installation_id != event.installation.id:
            receipt.reason = "unmapped_repository"
            session.add(receipt)
            return "unmapped"
        observed = session.scalar(
            select(ObservedEvent).where(
                ObservedEvent.source == "github",
                ObservedEvent.external_key == key,
            )
        )
        if observed is not None and (observed.org_id != mapping.org_id or observed.data != data):
            raise DeliveryConflictError("Workflow event conflict")
        if observed is None:
            observed = ObservedEvent(
                org_id=mapping.org_id,
                repository_id=mapping.repository_id,
                source="github",
                external_key=key,
                source_delivery_id=delivery_id,
                kind="workflow_run." + event.action,
                occurred_at=event.workflow_run.updated_at,
                data=data,
            )
            session.add(observed)
            session.flush()
            grouped = group_observation(session, observed)
            if grouped is not None and grouped.opened:
                _queue_opened_alerts(session, grouped.incident)
        receipt.state, receipt.reason = "accepted", None
        receipt.org_id, receipt.event_id = mapping.org_id, observed.id
        session.add(receipt)
        return "accepted"
