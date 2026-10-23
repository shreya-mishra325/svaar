"""Gateway polling/cursor coordination; injectable transports keep tests offline."""

import hashlib
import json
import logging
import threading
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from svaar.agent.models import GatewayCursor, InboundRecord, OutboxMessage
from svaar.agent.outbox import OutboxSender
from svaar.agent.runtime import ChatRuntime
from svaar.agent.transport import ChannelTransport

logger = logging.getLogger(__name__)


def stream_key(channel: str, connection_id: str) -> str:
    """Return a stable private stream key without logging connection identifiers."""
    return hashlib.sha256(json.dumps((channel, connection_id)).encode()).hexdigest()


class GatewayWorker:
    """One process-owned loop; stream ownership survives commits within turns."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        runtime: ChatRuntime,
        transport: ChannelTransport,
        *,
        channel: str,
        connection_id: str,
        poll_seconds: float = 2.0,
        batch_size: int = 10,
    ) -> None:
        self.sessions, self.runtime, self.transport = sessions, runtime, transport
        self.channel, self.connection_id = channel, connection_id
        self.poll_seconds, self.batch_size = poll_seconds, batch_size
        self.stream_key = stream_key(channel, connection_id)
        self.lock_key = int(self.stream_key[:16], 16) >> 1
        self.outbox = OutboxSender(
            sessions, transport, channel=channel, connection_id=connection_id
        )

    def _state(self, state: str, *, cursor: int | None = None, error: str | None = None) -> None:
        with self.sessions() as session:
            row = session.get(GatewayCursor, self.stream_key)
            if row is None:
                row = GatewayCursor(stream_key=self.stream_key, last_seq=0)
                session.add(row)
            row.state, row.error_code, row.heartbeat_at = state, error, datetime.now(UTC)
            if cursor is not None:
                row.last_seq = cursor
            session.commit()

    def tick(self) -> str:
        """Process a page, then advance its cursor; retries dedupe committed turns.

        A busy or untrusted message holds the cursor. No model or send is allowed
        for an untrusted page. A crash after replies commit but before cursor commit
        replays the page through inbound dedupe, never directly through tools.
        """
        with self.sessions() as locator:
            engine = locator.get_bind()
        with engine.connect() as connection:
            acquired = connection.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": self.lock_key}
            )
            if not acquired:
                return "busy"
            try:
                with self.sessions() as session:
                    row = session.get(GatewayCursor, self.stream_key)
                    after_seq = row.last_seq if row is not None else 0
                self._state("processing")
                batch = self.transport.poll(after_seq=after_seq, limit=self.batch_size)
                if batch.next_cursor < after_seq or (
                    batch.messages and batch.next_cursor == after_seq
                ):
                    raise ValueError("Cursor regression")
                for incoming in batch.messages:
                    if (
                        incoming.channel != self.channel
                        or incoming.connection_id != self.connection_id
                    ):
                        raise ValueError("Wrong transport route")
                # Validate the whole page before processing its first command.
                if any(not item.sender_authenticated for item in batch.messages):
                    self._state("blocked_identity", error="sender_identity_unverified")
                    return "blocked_identity"
                for incoming in batch.messages:
                    self._state("processing")
                    result = self.runtime.process(incoming)
                    if result.status == "busy":
                        self._state("processing", error="conversation_busy")
                        return "busy"
                    if result.status == "untrusted_sender":
                        self._state("blocked_identity", error="sender_identity_unverified")
                        return "blocked_identity"
                self._state("processing", cursor=batch.next_cursor)
                # Bounded work per tick; receipts are GETs and never re-POST.
                for _ in range(self.batch_size):
                    if self.outbox.send_one() is None:
                        break
                with self.sessions() as session:
                    queued = list(
                        session.scalars(
                            select(OutboxMessage.id)
                            .join(InboundRecord, InboundRecord.id == OutboxMessage.inbound_id)
                            .where(
                                OutboxMessage.state == "queued",
                                InboundRecord.channel == self.channel,
                                InboundRecord.connection_id == self.connection_id,
                            )
                            .limit(self.batch_size)
                        )
                    )
                for row_id in queued:
                    self.outbox.refresh(row_id)
                self._state("ready")
                return "ready"
            except Exception as exc:
                logger.error("gateway_tick_failed", extra={"error_type": type(exc).__name__})
                self._state("error", error="runtime_unavailable")
                return "error"
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": self.lock_key})

    def run(self, stop: threading.Event) -> None:
        """Wait interruptibly between ticks; bounded backoff on failures."""
        failures = 0
        try:
            while not stop.is_set():
                outcome = self.tick()
                failures = min(failures + 1, 4) if outcome == "error" else 0
                if stop.wait(min(self.poll_seconds * 2**failures, 30.0)):
                    break
        finally:
            self._state("stopped")
