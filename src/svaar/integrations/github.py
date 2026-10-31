"""Validate documented workflow_run payloads and atomically persist scoped observations."""

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from svaar.agent.notifications import enqueue_private_notification
from svaar.incidents.alerts import opened_alerts
from svaar.incidents.models import Incident, ObservedEvent
from svaar.incidents.service import group_observation
from svaar.integrations.models import RepoMapping, WebhookDelivery
from svaar.jobs.models import CiJob

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


class _Head(_Wire):
    sha: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    ref: str = Field(min_length=1, max_length=255)


class _PullRequest(_Wire):
    number: int = Field(gt=0, le=2147483647, strict=True)
    merged: bool = Field(strict=True)
    merged_at: AwareDatetime | None
    merge_commit_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{40,64}$")
    head: _Head
    base: _Head


class _PullRequestEvent(_Wire):
    action: str = Field(min_length=1, max_length=32)
    repository: _Identifier
    installation: _Identifier
    pull_request: _PullRequest


@dataclass(frozen=True)
class _Observation:
    """Normalized scope and identity shared by every supported event type."""

    repository_id: int
    installation_id: int
    kind: str
    occurred_at: datetime
    groupable: bool


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


def _normalize_merge(body: dict) -> tuple[_Observation | None, dict | None, str | None]:
    """Only a closed, merged pull request is an observation; other actions are ignored."""
    try:
        event = _PullRequestEvent.model_validate(body)
        pull = event.pull_request
        if event.action != "closed" or not pull.merged:
            return None, None, None
        if pull.merged_at is None or pull.merge_commit_sha is None:
            raise ValueError("Merged pull request without merge provenance")
    except (ValueError, TypeError, ValidationError, RecursionError):
        raise GithubPayloadError("Invalid webhook payload") from None
    occurred = pull.merged_at.astimezone(UTC)
    data = {
        "pull_number": pull.number,
        "merge_commit_sha": pull.merge_commit_sha,
        "head_sha": pull.head.sha,
        "head_branch": pull.head.ref,
        "base_branch": pull.base.ref,
        "merged_at": occurred.isoformat(),
    }
    key = f"pull_request:{event.repository.id}:{pull.number}:merged:{occurred.isoformat()}"
    observation = _Observation(
        event.repository.id, event.installation.id, "pull_request.merged", occurred, False
    )
    return observation, data, key


def _normalize(event_type: str, raw: bytes) -> tuple[_Observation | None, dict | None, str | None]:
    try:
        body = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_invalid_constant)
        if not isinstance(body, dict):
            raise ValueError("Object required")
    except (ValueError, TypeError, RecursionError):
        raise GithubJsonError("Invalid webhook JSON") from None
    if event_type == "pull_request":
        return _normalize_merge(body)
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
        observation = _Observation(
            event.repository.id,
            event.installation.id,
            "workflow_run." + event.action,
            run.updated_at,
            True,
        )
        return observation, data, key
    except (ValueError, TypeError, ValidationError, RecursionError):
        raise GithubPayloadError("Invalid webhook payload") from None


def queue_opened_alerts(session: Session, incident: Incident) -> None:
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
    *,
    defer_grouping: bool = False,
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
        mapping = session.get(RepoMapping, event.repository_id)
        if mapping is None or mapping.installation_id != event.installation_id:
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
                kind=event.kind,
                occurred_at=event.occurred_at,
                data=data,
            )
            session.add(observed)
            session.flush()
            # Merge facts are claim evidence found by query; they never open incidents.
            if event.groupable and defer_grouping:
                session.add(
                    CiJob(
                        event_id=observed.id,
                        org_id=mapping.org_id,
                        installation_id=mapping.installation_id,
                        owner_principal_id=mapping.owner_principal_id,
                    )
                )
            elif event.groupable:
                grouped = group_observation(
                    session, observed, owner_principal_id=mapping.owner_principal_id
                )
                if grouped is not None and grouped.opened:
                    queue_opened_alerts(session, grouped.incident)
        receipt.state, receipt.reason = "accepted", None
        receipt.org_id, receipt.event_id = mapping.org_id, observed.id
        session.add(receipt)
        return "accepted"
