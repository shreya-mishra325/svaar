"""Run and persist negotiations; re-validate proposals against a stored snapshot.

Callers own the transaction. Organization scope is checked for every lookup,
including the optional incident a negotiation belongs to.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from svaar.incidents.service import get_incident
from svaar.resolution.constraints import Constraints, Proposal
from svaar.resolution.models import Negotiation, NegotiationRound
from svaar.resolution.negotiation import Outcome, negotiate
from svaar.resolution.validator import ValidationResult, validate


class NegotiationNotFoundError(Exception):
    """No negotiation with that ID exists in the organization."""


def _violations(result: ValidationResult) -> list[dict[str, str]]:
    return [{"agent": v.agent.value, "code": v.code, "detail": v.detail} for v in result.violations]


def start_negotiation(
    session: Session,
    *,
    org_id: uuid.UUID,
    constraints: Constraints,
    proposal: Proposal,
    incident_id: uuid.UUID | None = None,
    constraints_revision: int | None = None,
) -> tuple[Negotiation, Outcome]:
    """Negotiate and store every round; raises IncidentNotFoundError for a foreign incident."""
    if incident_id is not None:
        get_incident(session, org_id, incident_id)
    outcome = negotiate(proposal, constraints)
    negotiation = Negotiation(
        org_id=org_id,
        incident_id=incident_id,
        constraints=constraints.model_dump(mode="json"),
        constraints_revision=constraints_revision,
        initial_proposal=proposal.model_dump(mode="json"),
        accepted_proposal=outcome.accepted.model_dump(mode="json") if outcome.accepted else None,
        state="accepted" if outcome.accepted else "rejected",
    )
    session.add(negotiation)
    session.flush()
    session.add_all(
        NegotiationRound(
            negotiation_id=negotiation.id,
            round_index=r.index,
            proposal=r.proposal.model_dump(mode="json"),
            revised_by=[agent.value for agent in r.revised_by],
            valid=r.result.valid,
            violations=_violations(r.result),
        )
        for r in outcome.rounds
    )
    session.flush()
    return negotiation, outcome


def get_negotiation(
    session: Session, org_id: uuid.UUID | None, negotiation_id: uuid.UUID
) -> tuple[Negotiation, list[NegotiationRound]]:
    """Return a negotiation and its rounds; org_id None is the operator's global view."""
    query = select(Negotiation).where(Negotiation.id == negotiation_id)
    if org_id is not None:
        query = query.where(Negotiation.org_id == org_id)
    negotiation = session.scalars(query).one_or_none()
    if negotiation is None:
        raise NegotiationNotFoundError("Negotiation not found")
    rounds = list(
        session.scalars(
            select(NegotiationRound)
            .where(NegotiationRound.negotiation_id == negotiation.id)
            .order_by(NegotiationRound.round_index)
        )
    )
    return negotiation, rounds


def validate_against(negotiation: Negotiation, proposal: Proposal) -> list[dict[str, str]]:
    """Validate a new proposal against the negotiation's stored constraint snapshot."""
    constraints = Constraints.model_validate(negotiation.constraints)
    return _violations(validate(proposal, constraints))
