"""Operator routes for negotiations and the deterministic validator."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from svaar.api.auth import require_operator
from svaar.api.errors import ErrorResponse
from svaar.db import get_session
from svaar.identity.service import get_org
from svaar.incidents.service import IncidentNotFoundError
from svaar.resolution import service
from svaar.resolution.constraints import Constraints, Proposal

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
