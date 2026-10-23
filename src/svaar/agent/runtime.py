"""Provider-independent durable chat coordinator; no listener is started here.

Verified transport identity is required even for invite redemption. Caspian's
current untrusted sender addresses are intentionally refused. Models and tool
handlers stay behind the existing AgentLoop/actions boundary.
"""

import hashlib
import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session, sessionmaker

from svaar.actions.registry import Channel, ToolContext
from svaar.agent.loop import HISTORY_LIMIT, AgentLoop
from svaar.agent.models import Conversation, InboundRecord, Message, OutboxMessage
from svaar.agent.transport import InboundMessage
from svaar.approvals.service import normalize_nonce
from svaar.identity.service import IdentityError, redeem_invite, resolve_principal


@dataclass(frozen=True)
class ProcessingResult:
    """Sanitized outcome; replies are delivered through the durable outbox."""

    status: str
    inbound_id: uuid.UUID | None = None


class ChatRuntime:
    """Serialize a private conversation across processes, including tool commits."""

    def __init__(self, sessions: sessionmaker[Session], agent: AgentLoop) -> None:
        self.sessions, self.agent = sessions, agent

    @contextmanager
    def _lock(self, incoming: InboundMessage) -> Iterator[bool]:
        # Session-level advisory locks live on a separate dedicated connection:
        # tier-2 dispatcher commits cannot release conversation ownership.
        keys = {
            ("sender", incoming.channel, incoming.sender_address),
            ("thread", incoming.channel, incoming.connection_id, incoming.thread_id),
            ("inbound", incoming.channel, incoming.connection_id, incoming.external_message_id),
        }
        numbers = sorted(
            {
                int.from_bytes(hashlib.sha256(json.dumps(key).encode()).digest()[:8], "big") >> 1
                for key in keys
            }
        )
        acquired = []
        with self.sessions() as locator:
            engine = locator.get_bind()
        with engine.connect() as connection:
            try:
                for number in numbers:
                    if not connection.scalar(
                        sql_text("SELECT pg_try_advisory_lock(:key)"), {"key": number}
                    ):
                        yield False
                        return
                    acquired.append(number)
                yield True
            finally:
                for number in reversed(acquired):
                    connection.execute(sql_text("SELECT pg_advisory_unlock(:key)"), {"key": number})

    def process(self, incoming: InboundMessage) -> ProcessingResult:
        """Process once; uncertain execution is never automatically repeated.

        A received marker is safe to resume. A processing marker means a previous
        run may have executed tools; duplicate delivery requests human review.
        Invite redemption, enrollment reply and its dedupe record commit together.
        """
        if not incoming.sender_authenticated:
            return ProcessingResult("untrusted_sender")
        if (
            not all(
                (
                    incoming.channel,
                    incoming.connection_id,
                    incoming.thread_id,
                    incoming.external_message_id,
                    incoming.sender_address,
                )
            )
            or len(incoming.channel) > 64
            or any(
                len(value) > 255
                for value in (
                    incoming.connection_id,
                    incoming.thread_id,
                    incoming.external_message_id,
                    incoming.sender_address,
                )
            )
            or not incoming.text.strip()
            or len(incoming.text) > 20000
        ):
            return ProcessingResult("invalid_message")
        with self._lock(incoming) as acquired:
            if not acquired:
                return ProcessingResult("busy")
            with self.sessions() as session:
                return self._process_locked(session, incoming)

    def _process_locked(self, session: Session, incoming: InboundMessage) -> ProcessingResult:
        payload_hash = hashlib.sha256(
            json.dumps((incoming.thread_id, incoming.sender_address, incoming.text)).encode()
        ).hexdigest()
        record = session.scalar(
            select(InboundRecord).where(
                InboundRecord.channel == incoming.channel,
                InboundRecord.connection_id == incoming.connection_id,
                InboundRecord.external_message_id == incoming.external_message_id,
            )
        )
        if record is not None:
            if record.payload_hash != payload_hash:
                return ProcessingResult("message_id_conflict")
            if record.state == "processed":
                return ProcessingResult("duplicate", record.id)
            if record.state in ("processing", "unknown"):
                record.state = "unknown"
                record.error_code = "reconciliation_required"
                session.commit()
                return ProcessingResult("reconciliation_required", record.id)

        principal = resolve_principal(session, incoming.channel, incoming.sender_address)
        # Never pass invite commands (including repeated joins) to the model/history.
        enrollment = incoming.text.strip().split(maxsplit=1)[0] == "/join"
        if principal is None:
            parts = incoming.text.strip().split()
            if len(parts) != 2 or parts[0] != "/join":
                return ProcessingResult("enrollment_required")
            try:
                principal = redeem_invite(
                    session,
                    code=parts[1],
                    channel=incoming.channel,
                    address=incoming.sender_address,
                    display_name="Team member",
                    sender_authenticated=True,
                )
            except IdentityError:
                session.rollback()
                return ProcessingResult("invite_rejected")
            enrollment = True

        conversation = session.scalar(
            select(Conversation).where(
                Conversation.channel == incoming.channel,
                Conversation.connection_id == incoming.connection_id,
                Conversation.thread_id == incoming.thread_id,
            )
        )
        if conversation is not None and (
            conversation.org_id != principal.org_id or conversation.principal_id != principal.id
        ):
            session.rollback()
            return ProcessingResult("thread_not_authorized")
        if conversation is None:
            conversation = Conversation(
                org_id=principal.org_id,
                principal_id=principal.id,
                channel=incoming.channel,
                connection_id=incoming.connection_id,
                thread_id=incoming.thread_id,
            )
            session.add(conversation)
            session.flush()
        if record is None:
            record = InboundRecord(
                conversation_id=conversation.id,
                channel=incoming.channel,
                connection_id=incoming.connection_id,
                external_message_id=incoming.external_message_id,
                sender_address=incoming.sender_address,
                payload_hash=payload_hash,
            )
            session.add(record)
            session.flush()
        elif record.conversation_id != conversation.id:
            session.rollback()
            return ProcessingResult("thread_not_authorized")

        if enrollment:
            self._enqueue(session, record.id, 0, "You are enrolled. You can now ask whoami.")
            record.state = "processed"
            session.commit()
            return ProcessingResult("enrolled", record.id)

        session.commit()  # received: no model/tool execution has started.
        record.state = "processing"
        session.commit()  # never replay automatically beyond this boundary.
        record_id, conversation_id = record.id, conversation.id
        try:
            recent = list(
                session.scalars(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.position.desc())
                    .limit(HISTORY_LIMIT)
                )
            )
            history = [{"role": row.role, "content": row.content} for row in reversed(recent)]
            result = self.agent.run(
                session,
                ToolContext(principal.org_id, principal.id, Channel.CHAT, None, str(record_id)),
                incoming.text,
                history=history,
            )
            safe_input = (
                "[confirmation input omitted]"
                if len(normalize_nonce(incoming.text)) == 6
                else incoming.text
            )
            session.add_all(
                [
                    Message(conversation_id=conversation_id, role="user", content=safe_input),
                    Message(
                        conversation_id=conversation_id, role="assistant", content=result.reply
                    ),
                ]
            )
            self._enqueue(session, record_id, 0, result.reply)
            for index, ticket in enumerate(result.tickets, start=1):
                if ticket.principal_id != principal.id:
                    raise ValueError("Invalid confirmation ticket owner")
                # Private outbox only, never Message/history/model context.
                self._enqueue(
                    session,
                    record_id,
                    index,
                    f"Confirmation code: {ticket.nonce}. It expires shortly.",
                )
            record.state = "processed"
            session.commit()
            return ProcessingResult("processed", record_id)
        except Exception:
            session.rollback()
            record = session.get(InboundRecord, record_id)
            record.state, record.error_code = "unknown", "reconciliation_required"
            session.commit()
            return ProcessingResult("reconciliation_required", record_id)

    @staticmethod
    def _enqueue(session: Session, inbound_id: uuid.UUID, ordinal: int, body: str) -> None:
        session.add(OutboxMessage(inbound_id=inbound_id, ordinal=ordinal, body=body))
