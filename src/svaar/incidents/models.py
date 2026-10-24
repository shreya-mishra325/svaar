"""Append-only observed source facts and the incidents that group them.

Observed events are never rewritten; incident membership lives in a separate link
table so grouping can change without touching recorded facts.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from svaar.db import Base


class IncidentState(StrEnum):
    """Lifecycle of an incident; only open and acknowledged incidents gather events."""

    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


ACTIVE_STATES = (IncidentState.OPEN.value, IncidentState.ACKNOWLEDGED.value)
_STATE_VALUES = ", ".join(f"'{state.value}'" for state in IncidentState)


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


class Incident(Base):
    """A failing CI workflow on one branch, grouped by a deterministic fingerprint.

    At most one active (open or acknowledged) incident exists per organization and
    fingerprint; later runs of the same workflow on the same branch join it.
    """

    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint(f"state IN ({_STATE_VALUES})", name="state_valid"),
        CheckConstraint("failure_count > 0", name="failure_count_positive"),
        Index(
            "uq_incidents_active_fingerprint",
            "org_id",
            "fingerprint",
            unique=True,
            postgresql_where=text("state IN ('open', 'acknowledged')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id"), index=True)
    repository_id: Mapped[int] = mapped_column(BigInteger)
    fingerprint: Mapped[str] = mapped_column(String(64))
    workflow_id: Mapped[int | None] = mapped_column(BigInteger)
    workflow_name: Mapped[str | None] = mapped_column(String(200))
    head_branch: Mapped[str | None] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(16), default=IncidentState.OPEN.value)
    failure_count: Mapped[int] = mapped_column(Integer, default=1)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IncidentEvent(Base):
    """Membership of one observed event in one incident."""

    __tablename__ = "incident_events"

    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id"), primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("events.id"), primary_key=True, unique=True
    )
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
