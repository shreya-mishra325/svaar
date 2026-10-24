"""Incident tools; registered with actions and invoked only through its dispatcher.

Every lookup is scoped to the caller's organization from trusted context, never
from an organization the model names.
"""

import uuid
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from svaar.actions.registry import ALL_ROLES, Channel, ToolCall, ToolSpec
from svaar.incidents import service
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
        "workflow": incident.workflow_name,
        "branch": incident.head_branch,
        "failures": incident.failure_count,
        "opened_at": incident.opened_at.isoformat(),
        "last_failure_at": incident.last_failure_at.isoformat(),
    }


def _resolve(call: ToolCall) -> Incident | None:
    assert isinstance(call.arguments, IncidentArguments)
    org_id = call.context.org_id
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
