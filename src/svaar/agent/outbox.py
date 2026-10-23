"""Durable outbox delivery, with bounded retries only for explicit safe rejection."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from svaar.agent.models import Conversation, InboundRecord, OutboxMessage
from svaar.agent.transport import (
    ChannelTransport,
    DeliveryRejectedError,
    InboundMessage,
)
from svaar.identity.service import resolve_principal


class OutboxSender:
    """A composition-owned worker; no automatic external calls occur at import."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        transport: ChannelTransport,
        *,
        channel: str,
        connection_id: str,
        max_attempts: int = 3,
    ) -> None:
        if not 1 <= max_attempts <= 5:
            raise ValueError("Use one to five delivery attempts")
        self.sessions, self.transport = sessions, transport
        self.channel, self.connection_id, self.max_attempts = channel, connection_id, max_attempts

    def send_one(self) -> uuid.UUID | None:
        """Claim one due reply. A crash in sending means unknown, never retry.

        Provider-queued records are never re-POSTed. A future receipt poller can
        reconcile them using delivery_id. Worker route selection is explicit.
        """
        with self.sessions() as session:
            row = session.scalar(
                select(OutboxMessage)
                .join(InboundRecord, InboundRecord.id == OutboxMessage.inbound_id)
                .where(
                    OutboxMessage.state == "pending",
                    OutboxMessage.next_attempt_at <= func.now(),
                    InboundRecord.channel == self.channel,
                    InboundRecord.connection_id == self.connection_id,
                    InboundRecord.state == "processed",
                )
                .order_by(OutboxMessage.created_at, OutboxMessage.ordinal)
                .with_for_update(of=OutboxMessage, skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            record = session.get(InboundRecord, row.inbound_id)
            conversation = session.get(Conversation, record.conversation_id)
            principal = resolve_principal(session, record.channel, record.sender_address)
            if principal is None or (
                principal.id != conversation.principal_id or principal.org_id != conversation.org_id
            ):
                row.state, row.error_code = "failed", "recipient_not_authorized"
                session.commit()
                return row.id
            target = InboundMessage(
                record.channel,
                record.connection_id,
                record.external_message_id,
                conversation.thread_id,
                record.sender_address,
                "",
                True,
            )
            row.state = "sending"
            row.attempts += 1
            session.commit()
            row_id = row.id
            try:
                receipt = self.transport.send(target, row.body)
            except DeliveryRejectedError as exc:
                retryable = getattr(exc, "retryable", False) and row.attempts < self.max_attempts
                row.state = "pending" if retryable else "failed"
                row.error_code = "delivery_rejected"
                row.next_attempt_at = datetime.now(UTC) + timedelta(seconds=2**row.attempts)
            except Exception:
                row.state, row.error_code = "unknown", "delivery_unknown"
            else:
                if receipt.status in ("sent", "delivered"):
                    row.state, row.sent_at = "sent", datetime.now(UTC)
                elif receipt.status == "queued":
                    row.state = "queued"
                else:
                    row.state, row.error_code = "failed", "provider_failed"
                row.delivery_id = receipt.delivery_id
            session.commit()
            return row_id

    def refresh(self, outbox_id: uuid.UUID) -> bool:
        """Reconcile an accepted delivery by GET, never by sending it again."""
        get_receipt = getattr(self.transport, "receipt", None)
        if get_receipt is None:
            return False
        with self.sessions() as session:
            row = session.scalar(
                select(OutboxMessage)
                .where(
                    OutboxMessage.id == outbox_id,
                    OutboxMessage.state == "queued",
                )
                .with_for_update(skip_locked=True)
            )
            if row is None or not row.delivery_id:
                return False
            record = session.get(InboundRecord, row.inbound_id)
            if record.channel != self.channel or record.connection_id != self.connection_id:
                return False
            conversation = session.get(Conversation, record.conversation_id)
            try:
                receipt = get_receipt(row.delivery_id, thread_id=conversation.thread_id)
            except Exception:
                session.rollback()
                return False
            if receipt.delivery_id != row.delivery_id:
                return False
            if receipt.status in ("sent", "delivered"):
                row.state, row.sent_at = "sent", datetime.now(UTC)
            elif receipt.status == "failed":
                row.state, row.error_code = "failed", "provider_failed"
            elif receipt.status != "queued":
                return False
            session.commit()
            return True
