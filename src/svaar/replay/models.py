"""Replay results live only here, never in observed events."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from svaar.db import Base


class ReplayRun(Base):
    """One simulated replay; the kind column can only ever say simulated."""

    __tablename__ = "replay_runs"
    __table_args__ = (CheckConstraint("kind = 'simulated'", name="kind_simulated"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id"), index=True)
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id"), index=True)
    negotiation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("negotiations.id"))
    kind: Mapped[str] = mapped_column(String(16), default="simulated")
    scenario: Mapped[dict[str, Any]] = mapped_column(JSONB)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
