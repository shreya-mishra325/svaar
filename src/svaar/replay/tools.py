"""Agent replay uses a fake simulator; proposed inputs never become observed facts."""

import uuid
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict

from svaar.actions.registry import Channel, ToolCall, ToolSpec
from svaar.identity.models import Role
from svaar.incidents.service import IncidentNotFoundError
from svaar.replay.service import run_replay
from svaar.replay.simulator import LABEL, Scenario
from svaar.resolution import service
from svaar.resolution.constraints import Proposal
from svaar.resolution.policy import MissingConstraintsError, load_constraints
from svaar.resolution.validator import validate


class ReplayArguments(BaseModel):
    """An explicitly hypothetical scenario associated with a current validated plan."""

    model_config = ConfigDict(extra="forbid")
    incident_id: uuid.UUID
    negotiation_id: uuid.UUID
    scenario: Scenario


def request_replay(call: ToolCall) -> Mapping[str, Any]:
    """Check organization, incident and current policy before isolated simulation."""
    assert isinstance(call.arguments, ReplayArguments)
    body = call.arguments
    if call.context.channel is Channel.VOICE and call.context.incident_id != body.incident_id:
        return {"simulated": False, "reason": "outside_call_incident"}
    try:
        rules, revision = load_constraints(call.session, call.context.org_id)
        negotiation, _ = service.get_negotiation(
            call.session, call.context.org_id, body.negotiation_id
        )
        if (
            negotiation.incident_id != body.incident_id
            or negotiation.state != "accepted"
            or negotiation.accepted_proposal is None
            or negotiation.constraints_revision != revision
        ):
            return {"simulated": False, "reason": "current_validated_plan_required"}
        proposal = Proposal.model_validate(negotiation.accepted_proposal)
        if proposal.approvals or not validate(proposal, rules).valid:
            return {"simulated": False, "reason": "proposal_invalid"}
        run = run_replay(call.session, call.context.org_id, body.incident_id, body.scenario)
    except (IncidentNotFoundError, service.NegotiationNotFoundError):
        return {"simulated": False, "reason": "not_found"}
    except MissingConstraintsError:
        return {"simulated": False, "reason": "constraints_not_configured"}
    run.negotiation_id = negotiation.id
    return {
        "simulated": True,
        "kind": "simulated",
        "label": LABEL,
        "inputs": "proposed scenario, not observed pipeline evidence",
        "replay_id": str(run.id),
        "negotiation_id": str(negotiation.id),
        "result": run.result,
    }


REQUEST_REPLAY = ToolSpec(
    name="request_replay",
    description="Simulate a proposed pipeline correction using fake adapters for an incident "
    "with a current validator-accepted negotiation. Ask for scenario details; do not "
    "invent recorded steps. All results are simulated, never production evidence.",
    arguments=ReplayArguments,
    handler=request_replay,
    roles=frozenset({Role.DEV, Role.LEAD, Role.ADMIN}),
    channels=frozenset(Channel),
)
