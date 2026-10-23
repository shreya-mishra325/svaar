"""Durable chat history, inbound processing and outbound delivery state."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from svaar.db import Base


class Conversation(Base):
    """A private thread bound to one principal and organization."""

    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("channel", "connection_id", "thread_id", name="uq_conversations_route"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id"), index=True)
    principal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"))
    channel: Mapped[str] = mapped_column(String(64))
    connection_id: Mapped[str] = mapped_column(String(255))
    thread_id: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    """History text only; confirmation tickets and invite codes never enter it."""

    __tablename__ = "messages"
    __table_args__ = (CheckConstraint("role IN ('user', 'assistant')", name="role_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), index=True)
    position: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InboundRecord(Base):
    """A committed processing marker prevents replay after an uncertain crash."""

    __tablename__ = "inbound_messages"
    __table_args__ = (
        UniqueConstraint(
            "channel", "connection_id", "external_message_id", name="uq_inbound_route"
        ),
        CheckConstraint(
            "state IN ('received', 'processing', 'processed', 'unknown')", name="state_valid"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), index=True)
    channel: Mapped[str] = mapped_column(String(64))
    connection_id: Mapped[str] = mapped_column(String(255))
    external_message_id: Mapped[str] = mapped_column(String(255))
    sender_address: Mapped[str] = mapped_column(String(255))
    payload_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16), default="received")
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutboxMessage(Base):
    """Pending/sending is persisted before network I/O; uncertain sends never retry."""

    __tablename__ = "outbox_messages"
    __table_args__ = (
        UniqueConstraint("inbound_id", "ordinal", name="uq_outbox_inbound_ordinal"),
        CheckConstraint(
            "state IN ('pending', 'sending', 'queued', 'sent', 'failed', 'unknown')",
            name="state_valid",
        ),
        CheckConstraint("attempts >= 0", name="attempts_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    inbound_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inbound_messages.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    delivery_id: Mapped[str | None] = mapped_column(String(255))
    error_code: Mapped[str | None] = mapped_column(String(64))
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GatewayCursor(Base):
    """Durable event-stream cursor and truthful process heartbeat."""

    __tablename__ = "gateway_cursors"
    __table_args__ = (
        CheckConstraint("last_seq >= 0", name="cursor_valid"),
        CheckConstraint(
            "state IN ('processing', 'ready', 'blocked_identity', 'error', 'stopped')",
            name="state_valid",
        ),
    )

    stream_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_seq: Mapped[int] = mapped_column(BigInteger, default=0)
    state: Mapped[str] = mapped_column(String(24), default="processing")
    error_code: Mapped[str | None] = mapped_column(String(64))
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
