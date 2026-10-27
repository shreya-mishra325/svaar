"""Persisted negotiations: the constraints negotiated against and every round's verdict."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from svaar.db import Base


class Negotiation(Base):
    """One negotiation over a snapshot of the three agents' hard constraints.

    Storing the snapshot keeps the verdict reproducible after constraints change.
    """

    __tablename__ = "negotiations"
    __table_args__ = (CheckConstraint("state IN ('accepted', 'rejected')", name="state_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id"), index=True)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("incidents.id"), index=True)
    constraints_revision: Mapped[int | None] = mapped_column(Integer)
    constraints: Mapped[dict[str, Any]] = mapped_column(JSONB)
    initial_proposal: Mapped[dict[str, Any]] = mapped_column(JSONB)
    accepted_proposal: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NegotiationRound(Base):
    """One proposal, which agents revised it, and the validator's violations."""

    __tablename__ = "negotiation_rounds"
    __table_args__ = (
        UniqueConstraint("negotiation_id", "round_index", name="uq_negotiation_rounds_index"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    negotiation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("negotiations.id"), index=True)
    round_index: Mapped[int] = mapped_column(Integer)
    proposal: Mapped[dict[str, Any]] = mapped_column(JSONB)
    revised_by: Mapped[list[str]] = mapped_column(JSONB)
    valid: Mapped[bool] = mapped_column(Boolean)
    violations: Mapped[list[dict[str, str]]] = mapped_column(JSONB)


class StandingConstraint(Base):
    """One operator-owned agent rule set; complete replacements share a revision."""

    __tablename__ = "constraints"
    __table_args__ = (
        UniqueConstraint("org_id", "owner_agent", name="uq_constraints_org_agent"),
        CheckConstraint("owner_agent IN ('release', 'staffing', 'capacity')", name="agent_valid"),
        CheckConstraint("revision > 0", name="revision_positive"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id"), index=True)
    owner_agent: Mapped[str] = mapped_column(String(16))
    rule: Mapped[dict[str, Any]] = mapped_column(JSONB)
    revision: Mapped[int] = mapped_column(Integer)


class ExceptionDraft(Base):
    """Server-generated tracked artifact; approval is not an external action."""

    __tablename__ = "exception_drafts"
    __table_args__ = (
        UniqueConstraint("negotiation_id", name="uq_exception_drafts_negotiation"),
        CheckConstraint("state IN ('draft', 'approved')", name="state_valid"),
        CheckConstraint("constraints_revision > 0", name="revision_positive"),
        CheckConstraint(
            "(state = 'draft' AND approved_by IS NULL AND approved_at IS NULL) OR "
            "(state = 'approved' AND approved_by IS NOT NULL AND approved_at IS NOT NULL)",
            name="approval_valid",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id"), index=True)
    negotiation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("negotiations.id"))
    constraints_revision: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(16), default="draft")
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
