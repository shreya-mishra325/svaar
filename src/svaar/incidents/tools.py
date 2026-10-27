"""Incident tools; registered with actions and invoked only through its dispatcher.

Every lookup is scoped to the caller's organization from trusted context, never
from an organization the model names.
"""

import uuid
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from svaar.actions.registry import ALL_ROLES, Channel, ToolCall, ToolSpec
from svaar.incidents import claims, service
from svaar.incidents.models import Incident

TIMELINE_LIMIT = 30


class IncidentArguments(BaseModel):
    """Optional incident ID; omitted means the most recently failing active incident."""

    model_config = {"extra": "forbid"}
    incident_id: uuid.UUID | None = Field(
        default=None, description="Incident ID; omit for the most recent active incident"
    )


class ListArguments(BaseModel):
    """Whether to include resolved incidents."""

    model_config = {"extra": "forbid"}
    include_resolved: bool = False


def _summary(incident: Incident) -> dict[str, Any]:
    return {
        "incident_id": str(incident.id),
        "state": incident.state,
        "owner_principal_id": str(incident.owner_principal_id)
        if incident.owner_principal_id
        else None,
        "workflow": incident.workflow_name,
        "branch": incident.head_branch,
        "failures": incident.failure_count,
        "opened_at": incident.opened_at.isoformat(),
        "last_failure_at": incident.last_failure_at.isoformat(),
    }


def _resolve(call: ToolCall) -> Incident | None:
    assert isinstance(call.arguments, IncidentArguments)
    org_id = call.context.org_id
    bound = call.context.incident_id if call.context.channel is Channel.VOICE else None
    if bound is not None:
        if call.arguments.incident_id not in {None, bound}:
            return None
        try:
            return service.get_incident(call.session, org_id, bound)
        except service.IncidentNotFoundError:
            return None
    if call.arguments.incident_id is None:
        return service.latest_active_incident(call.session, org_id)
    try:
        return service.get_incident(call.session, org_id, call.arguments.incident_id)
    except service.IncidentNotFoundError:
        return None


def get_timeline(call: ToolCall) -> Mapping[str, Any]:
    """Return an incident's recorded events in occurrence order."""
    incident = _resolve(call)
    if incident is None:
        return {"found": False}
    entries = service.timeline(call.session, call.context.org_id, incident.id)
    return {
        "found": True,
        "incident": _summary(incident),
        "events": [
            {
                "at": entry.occurred_at.isoformat(),
                "source": entry.source,
                "event": entry.kind,
                "run_id": entry.run_id,
                "attempt": entry.run_attempt,
                "status": entry.status,
                "conclusion": entry.conclusion,
            }
            for entry in entries[-TIMELINE_LIMIT:]
        ],
        "truncated": len(entries) > TIMELINE_LIMIT,
    }


def list_incidents(call: ToolCall) -> Mapping[str, Any]:
    """List the organization's incidents, most recently failing first."""
    assert isinstance(call.arguments, ListArguments)
    incidents = service.list_incidents(
        call.session, call.context.org_id, active_only=not call.arguments.include_resolved
    )
    return {"incidents": [_summary(incident) for incident in incidents]}


def acknowledge_incident(call: ToolCall) -> Mapping[str, Any]:
    """Acknowledge an open incident as the calling principal."""
    incident = _resolve(call)
    if incident is None:
        return {"found": False}
    incident, changed = service.acknowledge(
        call.session, call.context.org_id, incident.id, call.context.principal_id
    )
    return {"found": True, "acknowledged": changed, "incident": _summary(incident)}


GET_TIMELINE = ToolSpec(
    name="get_timeline",
    description=(
        "Show what happened in an incident: recorded CI events in the order they occurred. "
        "Omit incident_id for the most recent active incident."
    ),
    arguments=IncidentArguments,
    handler=get_timeline,
    roles=ALL_ROLES,
    channels=frozenset(Channel),
)

LIST_INCIDENTS = ToolSpec(
    name="list_incidents",
    description="List the team's incidents, most recently failing first.",
    arguments=ListArguments,
    handler=list_incidents,
    roles=ALL_ROLES,
    channels=frozenset({Channel.CHAT}),
)

ACKNOWLEDGE_INCIDENT = ToolSpec(
    name="acknowledge_incident",
    description=(
        "Acknowledge an open incident so escalation stops. "
        "Omit incident_id for the most recent active incident."
    ),
    arguments=IncidentArguments,
    handler=acknowledge_incident,
    roles=ALL_ROLES,
    channels=frozenset(Channel),
)


class CheckClaimArguments(BaseModel):
    """Select an existing claim in the caller's organization."""

    model_config = {"extra": "forbid"}
    claim_id: uuid.UUID


def record_claim(call: ToolCall) -> Mapping[str, Any]:
    """Record only the caller-bound author and trusted source correlation."""
    assert isinstance(call.arguments, claims.ClaimInput)
    try:
        claim = claims.record_claim(
            call.session,
            call.context.org_id,
            call.context.principal_id,
            call.arguments,
            call.context.correlation_id,
        )
    except service.IncidentNotFoundError:
        return {"found": False}
    except claims.ClaimConflictError:
        return {"error": "claim_source_conflict"}
    return {"found": True, "claim": claims.claim_summary(call.session, claim)}


def check_claim(call: ToolCall) -> Mapping[str, Any]:
    """Refresh status from deterministic evidence only."""
    assert isinstance(call.arguments, CheckClaimArguments)
    try:
        claim = claims.check_claim(call.session, call.context.org_id, call.arguments.claim_id)
    except (LookupError, service.IncidentNotFoundError):
        return {"found": False}
    return {"found": True, "claim": claims.claim_summary(call.session, claim)}


def list_claims(call: ToolCall) -> Mapping[str, Any]:
    """Read assertion/evidence distinctions without inferring truth."""
    incident = _resolve(call)
    if incident is None:
        return {"found": False}
    rows = claims.list_claims(call.session, call.context.org_id, incident.id)
    return {"found": True, "claims": [claims.claim_summary(call.session, row) for row in rows]}


RECORD_CLAIM = ToolSpec(
    "record_claim",
    "Record a caller's verifiable status assertion, not proof. Use the exact run and "
    "attempt for workflow success. Merge claims stay unverified without merge evidence.",
    claims.ClaimInput,
    record_claim,
    ALL_ROLES,
    frozenset({Channel.CHAT}),
)
CHECK_CLAIM = ToolSpec(
    "check_claim",
    "Check an existing claim against recorded evidence; missing facts are not denial.",
    CheckClaimArguments,
    check_claim,
    ALL_ROLES,
    frozenset({Channel.CHAT}),
)
LIST_CLAIMS = ToolSpec(
    "list_claims",
    "List incident claims with their status and evidence provenance.",
    IncidentArguments,
    list_claims,
    ALL_ROLES,
    frozenset(Channel),
)
