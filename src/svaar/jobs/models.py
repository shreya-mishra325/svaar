"""Durable local escalation work; these rows never authorize provider effects."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func
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
