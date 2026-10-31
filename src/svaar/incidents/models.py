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
    Text,
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
    owner_principal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
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


class WorkflowLogSignature(Base):
    """Append-only normalized digest, bound to one signed failed-run observation."""

    __tablename__ = "workflow_log_signatures"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "repository_id",
            "run_id",
            "run_attempt",
            "algorithm",
            name="uq_workflow_log_signatures_attempt",
        ),
        CheckConstraint(
            "repository_id > 0 AND run_id > 0 AND run_attempt > 0 AND "
            "workflow_id > 0 AND installation_id > 0",
            name="ids_positive",
        ),
        CheckConstraint("file_count > 0 AND file_count <= 100", name="files_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id"))
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id"), index=True)
    repository_id: Mapped[int] = mapped_column(BigInteger)
    installation_id: Mapped[int] = mapped_column(BigInteger)
    run_id: Mapped[int] = mapped_column(BigInteger)
    run_attempt: Mapped[int] = mapped_column(Integer)
    workflow_id: Mapped[int] = mapped_column(BigInteger)
    head_sha: Mapped[str] = mapped_column(String(64))
    head_branch: Mapped[str] = mapped_column(String(255))
    algorithm: Mapped[str] = mapped_column(String(32))
    digest: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64))
    file_count: Mapped[int] = mapped_column(Integer)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Claim(Base):
    """An authenticated principal's assertion; status is derived from evidence."""

    __tablename__ = "claims"
    __table_args__ = (
        UniqueConstraint("org_id", "source_key", name="uq_claims_org_source"),
        CheckConstraint(
            "status IN ('confirmed', 'contradicted', 'unverified')", name="status_valid"
        ),
        CheckConstraint("kind IN ('workflow_succeeded', 'fix_merged')", name="kind_valid"),
        CheckConstraint(
            "pull_number IS NULL OR kind = 'fix_merged'", name="pull_number_target_valid"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id"), index=True)
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id"), index=True)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    source_key: Mapped[str] = mapped_column(String(64))
    statement: Mapped[str] = mapped_column(String(4000))
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="unverified")
    run_id: Mapped[int | None] = mapped_column(BigInteger)
    run_attempt: Mapped[int | None] = mapped_column(Integer)
    head_sha: Mapped[str | None] = mapped_column(String(64))
    pull_number: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClaimEvidence(Base):
    """Append-only link to an observed fact, with the deterministic rule used."""

    __tablename__ = "evidence"
    __table_args__ = (
        UniqueConstraint("claim_id", "event_id", name="uq_evidence_claim_event"),
        UniqueConstraint("claim_id", "claim_answer_id", name="uq_evidence_claim_answer"),
        CheckConstraint("stance IN ('supports', 'contradicts')", name="stance_valid"),
        CheckConstraint("(event_id IS NULL) <> (claim_answer_id IS NULL)", name="one_source"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id"), index=True)
    claim_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claims.id"), index=True)
    event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("events.id"))
    claim_answer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("claim_answers.id"))
    stance: Mapped[str] = mapped_column(String(16))
    rule: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClaimAnswer(Base):
    """A claim author's answer from one claim_check call; never evidence by itself.

    The raw answer text is kept only until the completed call is classified, then
    purged; the hash, label and decision audit reference remain.
    """

    __tablename__ = "claim_answers"
    __table_args__ = (
        CheckConstraint(
            "state IN ('recorded', 'evidence', 'unverified', 'discarded')", name="state_valid"
        ),
        CheckConstraint("(state = 'recorded') = (answer_text IS NOT NULL)", name="retention_valid"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id"))
    claim_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claims.id"), index=True)
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("voice_calls.id"), unique=True)
    principal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    answer_hash: Mapped[str] = mapped_column(String(64))
    answer_text: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(16), default="recorded")
    label: Mapped[str | None] = mapped_column(String(16))
    decision_id: Mapped[uuid.UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
