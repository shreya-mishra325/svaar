"""Durable local escalation work; these rows never authorize provider effects."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from svaar.db import Base


class EscalationJob(Base):
    """One retryable preparation job and at most one call intent per incident."""

    __tablename__ = "escalation_jobs"
    __table_args__ = (
        CheckConstraint(
            "state IN ('waiting', 'deferred', 'prepared', 'canceled')", name="state_valid"
        ),
        CheckConstraint(
            "(state = 'prepared' AND call_id IS NOT NULL AND prepared_at IS NOT NULL) "
            "OR (state <> 'prepared' AND call_id IS NULL AND prepared_at IS NULL)",
            name="prepared_valid",
        ),
        Index("ix_escalation_jobs_recipient", "org_id", "principal_id", "prepared_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id"), unique=True)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id"))
    principal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    state: Mapped[str] = mapped_column(String(16), default="waiting")
    reason: Mapped[str | None] = mapped_column(String(64))
    next_check_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    call_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("voice_calls.id"), unique=True)
    prepared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CiJob(Base):
    """One leased grouping/enrichment task per immutable workflow observation."""

    __tablename__ = "ci_jobs"
    __table_args__ = (
        CheckConstraint("state IN ('pending', 'running', 'done', 'failed')", name="state_valid"),
        CheckConstraint("attempts >= 0", name="attempts_valid"),
        CheckConstraint(
            "(state = 'running' AND lease_token IS NOT NULL AND lease_until IS NOT NULL) OR "
            "(state <> 'running' AND lease_token IS NULL AND lease_until IS NULL)",
            name="lease_valid",
        ),
        Index("ix_ci_jobs_due", "state", "next_check_at", "lease_until"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id"), unique=True)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id"))
    installation_id: Mapped[int] = mapped_column(BigInteger)
    owner_principal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    state: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str | None] = mapped_column(String(64))
    next_check_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    lease_token: Mapped[uuid.UUID | None] = mapped_column()
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
