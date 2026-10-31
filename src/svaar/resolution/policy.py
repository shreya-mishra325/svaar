"""Operator-owned standing rules; chat models can propose plans but cannot set policy."""

import hashlib
import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from svaar.identity.service import get_org
from svaar.resolution.constraints import Agent, Constraints
from svaar.resolution.models import StandingConstraint


class MissingConstraintsError(Exception):
    """The organization does not have all three validated agent rule sets."""


class ConstraintRevisionConflictError(Exception):
    """A concurrent policy edit superseded the revision the operator reviewed."""


def lock_policy(session: Session, org_id: uuid.UUID) -> None:
    """Serialize policy reads used for decisions with operator replacements."""
    key = int.from_bytes(
        hashlib.sha256(f"constraints:{org_id}".encode()).digest()[:8], "big", signed=True
    )
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def load_constraints(session: Session, org_id: uuid.UUID) -> tuple[Constraints, int]:
    """Read a complete coherent operator-owned snapshot; never use empty defaults."""
    lock_policy(session, org_id)
    rows = list(
        session.scalars(
            select(StandingConstraint)
            .where(StandingConstraint.org_id == org_id)
            .order_by(StandingConstraint.owner_agent)
        )
    )
    if {row.owner_agent for row in rows} != {agent.value for agent in Agent} or len(
        {row.revision for row in rows}
    ) != 1:
        raise MissingConstraintsError("Configure all three agents' standing constraints")
    return Constraints.model_validate({row.owner_agent: row.rule for row in rows}), rows[0].revision


def replace_constraints(
    session: Session,
    org_id: uuid.UUID,
    rules: Constraints,
    *,
    expected_revision: int,
) -> int:
    """Atomically replace the complete set after an optimistic revision check."""
    if get_org(session, org_id) is None:
        raise MissingConstraintsError("Organization not found")
    lock_policy(session, org_id)
    rows = list(
        session.scalars(
            select(StandingConstraint).where(StandingConstraint.org_id == org_id).with_for_update()
        )
    )
    current = max((row.revision for row in rows), default=0)
    if expected_revision != current:
        raise ConstraintRevisionConflictError("Constraint revision changed")
    revision = current + 1
    by_agent = {row.owner_agent: row for row in rows}
    for agent, rule in rules.model_dump(mode="json").items():
        row = by_agent.get(agent)
        if row is None:
            row = StandingConstraint(org_id=org_id, owner_agent=agent)
            session.add(row)
        row.rule, row.revision = rule, revision
    session.flush()
    return revision
