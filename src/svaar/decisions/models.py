"""Decision audit: one row per question asked, including fallbacks."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from svaar.db import Base


class DecisionRecord(Base):
    """Audited answer; the state is stored only as a hash of its redacted text."""

    __tablename__ = "decisions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(index=True)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    state_hash: Mapped[str] = mapped_column(String(64))
    question: Mapped[str] = mapped_column(String(64))
    answer: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Float)
    probabilities: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    model_version: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16))
    fallback_reason: Mapped[str | None] = mapped_column(String(64))
    policy_outcome: Mapped[str] = mapped_column(String(16))
    action_taken: Mapped[str | None] = mapped_column(String(64))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
