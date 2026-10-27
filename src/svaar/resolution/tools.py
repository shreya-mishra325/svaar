"""Resolution tools load trusted policy and pass through the shared action gate."""

import uuid
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict

from svaar.actions.registry import Channel, ToolCall, ToolSpec
from svaar.identity.models import Role
from svaar.incidents.service import IncidentNotFoundError
from svaar.resolution import drafts, service
from svaar.resolution.constraints import Proposal
from svaar.resolution.policy import MissingConstraintsError, load_constraints


class NegotiationArguments(BaseModel):
    """A proposed plan; identity, standing constraints and approvals are server-owned."""

    model_config = ConfigDict(extra="forbid")
    incident_id: uuid.UUID
    proposal: Proposal


class DraftArguments(BaseModel):
    """The exact tracked draft whose approval needs owner confirmation."""

    model_config = ConfigDict(extra="forbid")
    draft_id: uuid.UUID


def start_negotiation(call: ToolCall) -> Mapping[str, Any]:
    """Negotiate using saved constraints and export the accepted tracked draft."""
    assert isinstance(call.arguments, NegotiationArguments)
    if call.arguments.proposal.approvals:
        return {"accepted": False, "reason": "unverified_approvals"}
    try:
        constraints, revision = load_constraints(call.session, call.context.org_id)
        negotiation, _ = service.start_negotiation(
            call.session,
            org_id=call.context.org_id,
            incident_id=call.arguments.incident_id,
            constraints=constraints,
            proposal=call.arguments.proposal,
            constraints_revision=revision,
        )
    except MissingConstraintsError:
        return {"accepted": False, "reason": "constraints_not_configured"}
    except IncidentNotFoundError:
        return {"accepted": False, "reason": "not_found"}
    _, rounds = service.get_negotiation(call.session, call.context.org_id, negotiation.id)
    draft = (
        drafts.create_draft(call.session, call.context.org_id, negotiation.id)
        if negotiation.state == "accepted"
        else None
    )
    return {
        "negotiation_id": str(negotiation.id),
        "accepted": negotiation.state == "accepted",
        "constraints_revision": revision,
        "proposal": negotiation.accepted_proposal,
        "draft_id": str(draft.id) if draft else None,
        "rounds": [
            {
                "index": row.round_index,
                "valid": row.valid,
                "revised_by": row.revised_by,
                "violations": row.violations,
            }
            for row in rounds
        ],
        "message": "Validator result only; no external action has run.",
    }


def approve_exception(call: ToolCall) -> Mapping[str, Any]:
    """Approve a local draft only after the dispatcher validates the owner's nonce."""
    assert isinstance(call.arguments, DraftArguments)
    try:
        return drafts.approve_draft(
            call.session, call.context.org_id, call.context.principal_id, call.arguments.draft_id
        )
    except MissingConstraintsError:
        return {"approved": False, "reason": "constraints_not_configured"}
    except service.NegotiationNotFoundError:
        return {"approved": False, "reason": "not_found"}


START_NEGOTIATION = ToolSpec(
    name="start_negotiation",
    description="Negotiate a concrete incident change against operator-saved release, staffing "
    "and capacity rules. Do not invent approval names. Returns validator rounds and "
    "a tracked draft for an accepted plan. No deployment or CI action runs.",
    arguments=NegotiationArguments,
    handler=start_negotiation,
    roles=frozenset({Role.LEAD, Role.ADMIN}),
    channels=frozenset({Channel.CHAT}),
)
APPROVE_EXCEPTION = ToolSpec(
    name="approve_exception",
    description="Request owner confirmation to approve an exact tracked exception draft. "
    "This approves the document only, never a policy waiver, deployment or CI action.",
    arguments=DraftArguments,
    handler=approve_exception,
    roles=frozenset({Role.LEAD, Role.ADMIN}),
    channels=frozenset({Channel.CHAT}),
    risk_tier=2,
)
