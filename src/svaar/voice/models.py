"""Server-owned call context and durable per-call turn results."""

import uuid
from datetime import datetime

from sqlalchemy import (
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
from sqlalchemy.orm import Mapped, mapped_column

from svaar.db import Base


class VoiceCall(Base):
    """An ordinary outbound call; creation and provider activation are not exposed yet."""

    __tablename__ = "voice_calls"
    __table_args__ = (
        Index(
            "uq_voice_calls_escalation_incident",
            "incident_id",
            unique=True,
            postgresql_where=text("mission = 'escalation' AND incident_id IS NOT NULL"),
        ),
        CheckConstraint(
            "(mission = 'phone_verify' AND phone_challenge_id IS NOT NULL "
            "AND phone_binding_id IS NULL) OR "
            "(mission <> 'phone_verify' AND phone_challenge_id IS NULL "
            "AND phone_binding_id IS NOT NULL)",
            name="phone_context_valid",
        ),
        CheckConstraint(
            "mission IN ('escalation', 'claim_check', 'confirmation', 'phone_verify')",
            name="mission_valid",
        ),
        CheckConstraint(
            "state IN ('pending', 'placing', 'queued', 'active', 'closed', 'failed', 'unknown')",
            name="state_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id"))
    principal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    incident_id: Mapped[uuid.UUID | None] = mapped_column()
    phone_binding_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("channel_bindings.id"))
    phone_challenge_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("phone_challenges.id"), unique=True
    )
    execution_id: Mapped[uuid.UUID | None] = mapped_column(unique=True)
    provider_agent_id: Mapped[uuid.UUID | None] = mapped_column()
    provider_status: Mapped[str | None] = mapped_column(String(32))
    call_ref_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    error_code: Mapped[str | None] = mapped_column(String(64))
    mission: Mapped[str] = mapped_column(String(24))
    state: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VoiceTurn(Base):
    """Processing/unknown markers never replay tools after an uncertain crash."""

    __tablename__ = "voice_turns"
    __table_args__ = (
        UniqueConstraint("voice_call_id", "turn_index", name="uq_voice_turns_call_index"),
        CheckConstraint("turn_index >= 0", name="index_valid"),
        CheckConstraint("state IN ('processing', 'processed', 'unknown')", name="state_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    voice_call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("voice_calls.id"), index=True)
    turn_index: Mapped[int] = mapped_column(Integer)
    payload_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16), default="processing")
    user_text: Mapped[str | None] = mapped_column(Text)
    reply: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VoiceWebhookEvent(Base):
    """Minimal durable status receipt; no transcript or extraction retention."""

    __tablename__ = "voice_webhook_events"
    __table_args__ = (
        UniqueConstraint("execution_id", "status", name="uq_voice_webhook_execution_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    voice_call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("voice_calls.id"))
    execution_id: Mapped[uuid.UUID] = mapped_column()
    status: Mapped[str] = mapped_column(String(32))
    payload_hash: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
