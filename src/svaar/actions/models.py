"""Execution audit: one row for every tool call attempt, allowed or not."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from svaar.db import Base


class ToolStatus(StrEnum):
    """Recorded outcome of a tool call.

    ``started`` is committed before a tier-2 handler runs. A row left in
    ``started`` after a crash, or a handler reporting ``outcome_unknown``, means the
    provider effect is uncertain; such actions are never retried automatically.
    """

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STARTED = "started"
    OUTCOME_UNKNOWN = "outcome_unknown"
    CONFIRMATION_REQUIRED = "confirmation_required"
    INVALID_ARGUMENTS = "invalid_arguments"
    DENIED = "denied"
    UNKNOWN_TOOL = "unknown_tool"


STATUS_VALUES = ", ".join(f"'{status.value}'" for status in ToolStatus)


class ToolExecution(Base):
    """Audit row; arguments are stored only as a hash."""

    __tablename__ = "tool_executions"
    __table_args__ = (CheckConstraint(f"status IN ({STATUS_VALUES})", name="status_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(index=True)
    principal_id: Mapped[uuid.UUID] = mapped_column(index=True)
    tool: Mapped[str] = mapped_column(String(64))
    args_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    risk_tier: Mapped[int | None] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(16))
    mission: Mapped[str | None] = mapped_column(String(32))
    correlation_id: Mapped[str] = mapped_column(String(128), index=True)
    confirmation_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    # Set to the confirmation ID for confirmed tier-2 runs, so each runs at most once.
    execution_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
