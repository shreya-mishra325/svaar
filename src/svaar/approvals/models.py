"""Confirmation table for tier-2 actions."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from svaar.db import Base


class ConfirmationState(StrEnum):
    """Lifecycle of a confirmation; only ``pending`` can change."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    DENIED = "denied"
    EXPIRED = "expired"
    LOCKED = "locked"


STATE_VALUES = ", ".join(f"'{state.value}'" for state in ConfirmationState)


class Confirmation(Base):
    """A pending tier-2 action bound to its owner, arguments and expiry.

    Identifiers are plain values; approvals does not import identity or actions models.
    """

    __tablename__ = "confirmations"
    __table_args__ = (CheckConstraint(f"state IN ({STATE_VALUES})", name="state_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(index=True)
    principal_id: Mapped[uuid.UUID] = mapped_column(index=True)
    action: Mapped[str] = mapped_column(String(64))
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB)
    action_hash: Mapped[str] = mapped_column(String(64))
    nonce_hash: Mapped[str] = mapped_column(String(64))
    requested_channel: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(16), default=ConfirmationState.PENDING.value)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_channel: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
