"""Read-only CI tools over accepted observations; never infer current provider state."""

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from svaar.actions.registry import Channel, ToolCall, ToolSpec
from svaar.identity.models import Role
from svaar.incidents.fingerprints import ALGORITHM
from svaar.incidents.models import Incident, IncidentEvent, ObservedEvent, WorkflowLogSignature
from svaar.incidents.service import FAILURE_CONCLUSIONS
from svaar.integrations.models import RepoMapping, WebhookDelivery


class RunsArguments(BaseModel):
    """An explicitly mapped repository, with a bounded result count."""

    model_config = ConfigDict(extra="forbid")
    repository_id: int = Field(gt=0, le=9223372036854775807, strict=True)
    limit: int = Field(default=10, ge=1, le=20, strict=True)


class FailureArguments(BaseModel):
    """An exact workflow attempt, never a model-selected URL or organization."""

    model_config = ConfigDict(extra="forbid")
    repository_id: int = Field(gt=0, le=9223372036854775807, strict=True)
    run_id: int = Field(gt=0, le=9223372036854775807, strict=True)
    run_attempt: int = Field(gt=0, le=2147483647, strict=True)


def _observed(call: ToolCall, repository_id: int):
    """Require both the current same-org mapping and original accepted receipt."""
    return (
        select(ObservedEvent)
        .join(WebhookDelivery, WebhookDelivery.id == ObservedEvent.source_delivery_id)
        .join(RepoMapping, RepoMapping.repository_id == ObservedEvent.repository_id)
        .where(
            ObservedEvent.org_id == call.context.org_id,
            ObservedEvent.repository_id == repository_id,
            ObservedEvent.source == "github",
            ObservedEvent.kind.in_(
                ("workflow_run.requested", "workflow_run.in_progress", "workflow_run.completed")
            ),
            RepoMapping.org_id == call.context.org_id,
            WebhookDelivery.state == "accepted",
            WebhookDelivery.event_id == ObservedEvent.id,
            WebhookDelivery.org_id == call.context.org_id,
        )
    )


def _summary(event: ObservedEvent) -> dict[str, Any]:
    return {
        "event_id": str(event.id),
        "run_id": event.data["run_id"],
        "run_attempt": event.data["run_attempt"],
        "workflow": event.data.get("workflow_name"),
        "branch": event.data.get("head_branch"),
        "status": event.data["status"],
        "conclusion": event.data.get("conclusion"),
        "occurred_at": event.occurred_at.isoformat(),
    }


def list_ci_runs(call: ToolCall) -> Mapping[str, Any]:
    """Return latest recorded transition per attempt, explicitly not a live REST refresh."""
    assert isinstance(call.arguments, RunsArguments)
    # Rank in PostgreSQL before limiting, so a noisy run cannot hide other attempts.
    statement = _observed(call, call.arguments.repository_id)
    ranked = statement.with_only_columns(
        ObservedEvent.id,
        func.row_number()
        .over(
            partition_by=(
                ObservedEvent.data["run_id"].astext,
                ObservedEvent.data["run_attempt"].astext,
            ),
            order_by=(
                ObservedEvent.occurred_at.desc(),
                ObservedEvent.received_at.desc(),
                ObservedEvent.id,
            ),
        )
        .label("rank"),
    ).subquery()
    events = call.session.scalars(
        select(ObservedEvent)
        .join(ranked, ranked.c.id == ObservedEvent.id)
        .where(ranked.c.rank == 1)
        .order_by(ObservedEvent.occurred_at.desc(), ObservedEvent.id)
        .limit(call.arguments.limit)
    )
    return {
        "source": "accepted GitHub webhook observations",
        "live_refresh": False,
        "runs": [_summary(event) for event in events],
        "message": "Recorded attempts only; absence or success does not prove current recovery.",
    }


def explain_ci_failure(call: ToolCall) -> Mapping[str, Any]:
    """Separate observed failure and log fingerprint evidence from an unknown root cause."""
    assert isinstance(call.arguments, FailureArguments)
    body = call.arguments
    event = call.session.scalar(
        _observed(call, body.repository_id)
        .where(
            ObservedEvent.kind == "workflow_run.completed",
            ObservedEvent.data["run_id"].astext == str(body.run_id),
            ObservedEvent.data["run_attempt"].astext == str(body.run_attempt),
        )
        .order_by(
            ObservedEvent.occurred_at.desc(), ObservedEvent.received_at.desc(), ObservedEvent.id
        )
        .limit(1)
    )
    if event is None:
        return {"found": False}
    incident = call.session.scalar(
        select(Incident)
        .join(IncidentEvent, IncidentEvent.incident_id == Incident.id)
        .where(IncidentEvent.event_id == event.id, Incident.org_id == call.context.org_id)
    )
    signature = call.session.scalar(
        select(WorkflowLogSignature).where(
            WorkflowLogSignature.org_id == call.context.org_id,
            WorkflowLogSignature.repository_id == body.repository_id,
            WorkflowLogSignature.run_id == body.run_id,
            WorkflowLogSignature.run_attempt == body.run_attempt,
            WorkflowLogSignature.head_sha == event.data["head_sha"],
            WorkflowLogSignature.algorithm == ALGORITHM,
        )
    )
    return {
        "found": True,
        "observation": _summary(event),
        "failed": event.data.get("conclusion") in FAILURE_CONCLUSIONS,
        "incident_id": str(incident.id) if incident else None,
        "log_signature": {
            "algorithm": signature.algorithm,
            "digest": signature.digest,
            "provenance_event_id": str(signature.event_id),
        }
        if signature
        else None,
        "repository_id": body.repository_id,
        "installation_id": call.session.get(RepoMapping, body.repository_id).installation_id,
        "category": "unknown",
        "cause_established": False,
        "message": "A fingerprint groups matching log tails; it does not identify a root cause. "
        "No CI action ran and no production recovery was inferred.",
    }


CI_ROLES = frozenset({Role.DEV, Role.LEAD, Role.ADMIN})
LIST_CI_RUNS = ToolSpec(
    name="list_ci_runs",
    description="List recorded workflow attempts for an explicitly mapped "
    "repository. Uses accepted webhook observations, not a live GitHub refresh.",
    arguments=RunsArguments,
    handler=list_ci_runs,
    roles=CI_ROLES,
    channels=frozenset({Channel.CHAT}),
)
EXPLAIN_CI_FAILURE = ToolSpec(
    name="explain_ci_failure",
    description="Inspect the exact recorded workflow attempt and "
    "available log fingerprint provenance. Root cause/category remain unknown without evidence; "
    "this cannot rerun a workflow or prove recovery.",
    arguments=FailureArguments,
    handler=explain_ci_failure,
    roles=CI_ROLES,
    channels=frozenset({Channel.CHAT}),
)
