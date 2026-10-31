"""Tracked change artifacts and local confirmation-gated approval, never deployment."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from svaar.identity.service import get_principal
from svaar.resolution import service
from svaar.resolution.constraints import Proposal
from svaar.resolution.models import ExceptionDraft
from svaar.resolution.policy import load_constraints
from svaar.resolution.validator import validate

LABEL = "Tracked exception draft only; not legal advice, a policy waiver or deployment approval."


def create_draft(session: Session, org_id: uuid.UUID, negotiation_id: uuid.UUID) -> ExceptionDraft:
    """Export a validator-accepted plan against current trusted rules as tracked changes."""
    negotiation, rounds = service.get_negotiation(session, org_id, negotiation_id)
    rules, revision = load_constraints(session, org_id)
    if (
        negotiation.state != "accepted"
        or negotiation.accepted_proposal is None
        or negotiation.constraints_revision != revision
    ):
        raise ValueError("A current standing-policy negotiation must be accepted first")
    proposal = Proposal.model_validate(negotiation.accepted_proposal)
    if proposal.approvals or not validate(proposal, rules).valid:
        raise ValueError("The proposal is not valid under current trusted rules")
    existing = session.scalar(
        select(ExceptionDraft).where(
            ExceptionDraft.org_id == org_id, ExceptionDraft.negotiation_id == negotiation_id
        )
    )
    if existing is not None:
        return existing
    before = dict(negotiation.initial_proposal)
    after = dict(negotiation.accepted_proposal)
    draft = ExceptionDraft(
        org_id=org_id,
        negotiation_id=negotiation.id,
        constraints_revision=revision,
        state="draft",
        content={
            "kind": "exception_draft",
            "label": LABEL,
            "before": before,
            "after": after,
            "changes": [
                {"field": key, "before": before.get(key), "after": after.get(key)}
                for key in sorted(after)
                if before.get(key) != after.get(key)
            ],
            "rounds": [
                {"index": row.round_index, "valid": row.valid, "violations": row.violations}
                for row in rounds
            ],
        },
    )
    session.add(draft)
    session.flush()
    return draft


def approve_draft(
    session: Session,
    org_id: uuid.UUID,
    principal_id: uuid.UUID,
    draft_id: uuid.UUID,
) -> dict:
    """Recheck policy and plan at execution; authorize only this local artifact."""
    rules, revision = load_constraints(session, org_id)
    draft = session.scalar(
        select(ExceptionDraft)
        .where(ExceptionDraft.id == draft_id, ExceptionDraft.org_id == org_id)
        .with_for_update()
    )
    if draft is None or get_principal(session, org_id, principal_id) is None:
        return {"approved": False, "reason": "not_found"}
    if draft.state == "approved":
        return {
            "approved": True,
            "already_approved": True,
            "draft_id": str(draft.id),
            "label": LABEL,
        }
    negotiation, _ = service.get_negotiation(session, org_id, draft.negotiation_id)
    if (
        revision != draft.constraints_revision
        or revision != negotiation.constraints_revision
        or negotiation.state != "accepted"
        or negotiation.accepted_proposal != draft.content.get("after")
        or negotiation.initial_proposal != draft.content.get("before")
    ):
        return {"approved": False, "reason": "renegotiation_required"}
    proposal = Proposal.model_validate(negotiation.accepted_proposal)
    if proposal.approvals or not validate(proposal, rules).valid:
        return {"approved": False, "reason": "proposal_invalid"}
    draft.state, draft.approved_by, draft.approved_at = "approved", principal_id, func.now()
    session.flush()
    return {"approved": True, "draft_id": str(draft.id), "label": LABEL}
