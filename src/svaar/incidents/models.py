"""Append-only observed source facts; no incident or claim state is inferred here."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from svaar.db import Base


class ObservedEvent(Base):
    """Normalized GitHub observation, with original delivery provenance."""

    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("source", "external_key", name="uq_events_source_external_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id"), index=True)
    repository_id: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(32))
    external_key: Mapped[str] = mapped_column(String(255))
    source_delivery_id: Mapped[uuid.UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
