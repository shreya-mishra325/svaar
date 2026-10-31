"""Operator routes for negotiations and the deterministic validator."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from svaar.api.auth import require_operator
from svaar.api.errors import ErrorResponse
from svaar.db import get_session
from svaar.identity.service import get_org
from svaar.incidents.service import IncidentNotFoundError
from svaar.resolution import drafts, policy, service
from svaar.resolution.constraints import Constraints, Proposal
from svaar.resolution.models import ExceptionDraft

router = APIRouter(
    tags=["resolution"],
    dependencies=[Depends(require_operator)],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
SessionDep = Annotated[Session, Depends(get_session)]


class NegotiationCreate(BaseModel):
    """Constraints to negotiate against and the initial proposal."""

    model_config = ConfigDict(extra="forbid")
    org_id: uuid.UUID
    incident_id: uuid.UUID | None = None
    constraints: Constraints
    proposal: Proposal


class RoundOut(BaseModel):
    """One round's proposal and verdict."""

    round_index: int
    proposal: dict[str, Any]
    revised_by: list[str]
    valid: bool
    violations: list[dict[str, str]]


class NegotiationOut(BaseModel):
    """A negotiation and every round in order."""

    id: uuid.UUID
    org_id: uuid.UUID
    incident_id: uuid.UUID | None
    state: str
    accepted_proposal: dict[str, Any] | None
    rounds: list[RoundOut]


class ValidationOut(BaseModel):
    """Validator verdict for one proposal."""

    valid: bool
    violations: list[dict[str, str]]


def _out(negotiation, rounds) -> NegotiationOut:
    return NegotiationOut(
        id=negotiation.id,
        org_id=negotiation.org_id,
        incident_id=negotiation.incident_id,
        state=negotiation.state,
        accepted_proposal=negotiation.accepted_proposal,
        rounds=[RoundOut.model_validate(r, from_attributes=True) for r in rounds],
    )


@router.post("/negotiations", status_code=status.HTTP_201_CREATED, response_model=NegotiationOut)
def create_negotiation(body: NegotiationCreate, session: SessionDep) -> NegotiationOut:
    """Run a bounded negotiation and store every round."""
    if get_org(session, body.org_id) is None:
        raise HTTPException(404)
    try:
        negotiation, _ = service.start_negotiation(
            session,
            org_id=body.org_id,
            constraints=body.constraints,
            proposal=body.proposal,
            incident_id=body.incident_id,
        )
    except IncidentNotFoundError:
        raise HTTPException(404) from None
    session.commit()
    return _out(*service.get_negotiation(session, body.org_id, negotiation.id))


@router.get("/negotiations/{negotiation_id}", response_model=NegotiationOut)
def read_negotiation(negotiation_id: uuid.UUID, session: SessionDep) -> NegotiationOut:
    """Return a stored negotiation."""
    try:
        return _out(*service.get_negotiation(session, None, negotiation_id))
    except service.NegotiationNotFoundError:
        raise HTTPException(404) from None


@router.post("/negotiations/{negotiation_id}/validate", response_model=ValidationOut)
def validate_proposal(
    negotiation_id: uuid.UUID, proposal: Proposal, session: SessionDep
) -> ValidationOut:
    """Validate a proposal against the negotiation's constraints; nothing is stored."""
    try:
        negotiation, _ = service.get_negotiation(session, None, negotiation_id)
    except service.NegotiationNotFoundError:
        raise HTTPException(404) from None
    violations = service.validate_against(negotiation, proposal)
    return ValidationOut(valid=not violations, violations=violations)


class ConstraintsReplace(BaseModel):
    """A complete operator-reviewed policy replacement, checked against its revision."""

    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0, le=2147483646, strict=True)
    constraints: Constraints


class ConstraintsOut(BaseModel):
    """Current trusted policy and its revision for optimistic updates."""

    org_id: uuid.UUID
    revision: int
    constraints: Constraints


@router.put("/orgs/{org_id}/constraints", response_model=ConstraintsOut)
def replace_standing_constraints(
    org_id: uuid.UUID,
    body: ConstraintsReplace,
    session: SessionDep,
) -> ConstraintsOut:
    """Operator-only replacement; chat tools cannot alter hard constraints."""
    if get_org(session, org_id) is None:
        raise HTTPException(404)
    try:
        revision = policy.replace_constraints(
            session, org_id, body.constraints, expected_revision=body.expected_revision
        )
    except policy.ConstraintRevisionConflictError:
        raise HTTPException(409, "Constraint revision changed") from None
    session.commit()
    return ConstraintsOut(org_id=org_id, revision=revision, constraints=body.constraints)


@router.get("/orgs/{org_id}/constraints", response_model=ConstraintsOut)
def read_standing_constraints(org_id: uuid.UUID, session: SessionDep) -> ConstraintsOut:
    """Read the coherent standing snapshot; absent policy has no permissive defaults."""
    try:
        constraints, revision = policy.load_constraints(session, org_id)
    except policy.MissingConstraintsError:
        raise HTTPException(404) from None
    return ConstraintsOut(org_id=org_id, revision=revision, constraints=constraints)


@router.post("/negotiations/{negotiation_id}/exception-draft", status_code=201)
def export_exception_draft(negotiation_id: uuid.UUID, session: SessionDep) -> dict[str, Any]:
    """Export tracked JSON changes; legacy request-scoped policies cannot approve drafts."""
    try:
        negotiation, _ = service.get_negotiation(session, None, negotiation_id)
        draft = drafts.create_draft(session, negotiation.org_id, negotiation.id)
    except (service.NegotiationNotFoundError, policy.MissingConstraintsError):
        raise HTTPException(404) from None
    except ValueError:
        raise HTTPException(409, "A current standing-policy accepted plan is required") from None
    session.commit()
    return {"id": str(draft.id), "state": draft.state, "content": draft.content}


@router.get("/exception-drafts/{draft_id}")
def read_exception_draft(draft_id: uuid.UUID, session: SessionDep) -> dict[str, Any]:
    """Operator download view; changing approval requires the shared action gate."""
    draft = session.get(ExceptionDraft, draft_id)
    if draft is None:
        raise HTTPException(404)
    return {
        "id": str(draft.id),
        "org_id": str(draft.org_id),
        "negotiation_id": str(draft.negotiation_id),
        "state": draft.state,
        "constraints_revision": draft.constraints_revision,
        "approved_by": str(draft.approved_by) if draft.approved_by else None,
        "approved_at": draft.approved_at.isoformat() if draft.approved_at else None,
        "content": draft.content,
    }
