"""Internal voice orchestration with an injected shared-agent executor.

No provider routes, call placement or asserted caller identities are accepted here.
The transport must authenticate and resolve an internal call ID before invocation.
"""

import hashlib
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session, sessionmaker

from svaar.actions.missions import Mission
from svaar.actions.registry import Channel, ToolContext
from svaar.identity.models import ChannelBinding
from svaar.identity.phones import pending_phone, phone_challenge_state
from svaar.identity.service import get_principal
from svaar.voice.models import VoiceCall, VoiceTurn

REFUSAL = "I can't access that call."
FALLBACK = "I can't check that right now. Please continue in chat."
QUEUED_FALLBACK = "I can't check that right now. I have queued a private chat follow-up."
Executor = Callable[[Session, ToolContext, str, Sequence[Mapping[str, Any]]], tuple[str, str]]


class VoiceRuntime:
    """Persist one result per server-resolved call/turn, with bounded private history."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        execute: Executor,
        *,
        notify_failure: Callable[[Session, uuid.UUID, uuid.UUID, uuid.UUID, int], bool]
        | None = None,
    ) -> None:
        self.sessions, self.execute = sessions, execute
        self.notify_failure = notify_failure

    def _failure_reply(self, session: Session, call: VoiceCall, index: int) -> str:
        """Queue a generic follow-up atomically; never promise delivery without a route."""
        if self.notify_failure is not None:
            try:
                with session.begin_nested():
                    queued = self.notify_failure(
                        session,
                        call.org_id,
                        call.principal_id,
                        call.id,
                        index,
                    )
                if queued:
                    return QUEUED_FALLBACK
            except Exception:
                # Notification failure must not undo an uncertain execution marker.
                pass
        return FALLBACK

    def run_turn(self, call_id: str, text: str, *, turn_index: int | None = None) -> str:
        """Run or reuse a turn; missing stable indices never execute the agent.

        Indices start at zero and increase without gaps. Equal text at a new index
        is a new utterance, not a retry. Processing/unknown turns require review.
        """
        try:
            identifier = uuid.UUID(call_id)
        except (ValueError, TypeError, AttributeError):
            return REFUSAL
        if (
            type(turn_index) is not int
            or not 0 <= turn_index <= 2147483647
            or not isinstance(text, str)
            or not text.strip()
            or len(text) > 20000
        ):
            return REFUSAL
        key = int.from_bytes(
            hashlib.sha256(b"voice:" + identifier.bytes).digest()[:8], "big", signed=True
        )
        with self.sessions() as locator:
            engine = locator.get_bind()
        # A dedicated session-level lock survives dispatcher commits.
        with engine.connect() as connection:
            acquired = connection.scalar(
                sql_text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
            )
            if not acquired:
                return FALLBACK
            try:
                with self.sessions() as session:
                    return self._run_locked(session, identifier, text, turn_index)
            finally:
                connection.execute(sql_text("SELECT pg_advisory_unlock(:key)"), {"key": key})

    def _run_locked(self, session: Session, call_id: uuid.UUID, text: str, index: int) -> str:
        call = session.get(VoiceCall, call_id)
        if call is None or call.state not in {"active", "closed"}:
            return REFUSAL
        existing = session.scalar(
            select(VoiceTurn).where(
                VoiceTurn.voice_call_id == call.id, VoiceTurn.turn_index == index
            )
        )
        if call.state == "closed" and existing is None:
            return REFUSAL
        principal = get_principal(session, call.org_id, call.principal_id)
        verification = call.mission == Mission.PHONE_VERIFY.value
        if verification:
            authorized = (
                pending_phone(
                    session,
                    org_id=call.org_id,
                    principal_id=call.principal_id,
                    challenge_id=call.phone_challenge_id,
                )
                is not None
            )
            if not authorized and existing is not None and existing.state == "processed":
                authorized = phone_challenge_state(
                    session,
                    org_id=call.org_id,
                    principal_id=call.principal_id,
                    challenge_id=call.phone_challenge_id,
                ) in {"verified", "locked", "expired"}
        else:
            binding = session.get(ChannelBinding, call.phone_binding_id)
            authorized = (
                binding is not None
                and binding.channel == "phone"
                and binding.principal_id == call.principal_id
                and binding.verified_at is not None
            )
        if principal is None or not authorized:
            return REFUSAL
        fingerprint = hashlib.sha256(text.encode()).hexdigest()
        turns = list(
            session.scalars(
                select(VoiceTurn)
                .where(VoiceTurn.voice_call_id == call.id)
                .order_by(VoiceTurn.turn_index.desc())
                .limit(6)
            )
        )
        if existing is not None:
            if existing.payload_hash != fingerprint:
                return REFUSAL
            if existing.state == "processed" and existing.reply:
                return existing.reply
            reply = self._failure_reply(session, call, index)
            session.commit()
            return reply
        if any(turn.state != "processed" for turn in turns):
            return FALLBACK
        if index != (turns[0].turn_index + 1 if turns else 0):
            return REFUSAL
        mission = Mission(call.mission)
        context = ToolContext(
            call.org_id,
            call.principal_id,
            Channel.VOICE,
            mission,
            f"voice:{call.id}:{index}",
            phone_challenge_id=call.phone_challenge_id,
        )
        history = [
            {"role": role, "content": content}
            for turn in reversed(turns)
            for role, content in (("user", turn.user_text), ("assistant", turn.reply))
            if content
        ]
        if verification:
            # A prior assistant may have echoed digits. No verification utterance
            # or reply is replayed to the model; saved replies remain retryable.
            history = []
        turn = VoiceTurn(voice_call_id=call.id, turn_index=index, payload_hash=fingerprint)
        session.add(turn)
        session.commit()  # Durable before any tools or inference.
        try:
            reply, reason = self.execute(session, context, text, history)
            if not isinstance(reply, str) or not reply.strip():
                raise ValueError("Invalid agent reply")
            if reason in {"unavailable", "tool_limit"}:
                reply = self._failure_reply(session, call, index)
            # Unusable speech and spoken codes do not enter later prompts.
            sensitive = len(re.sub(r"\D", "", text)) == 6 or mission in {
                Mission.CONFIRMATION,
                Mission.PHONE_VERIFY,
            }
            turn.user_text = (
                "[confirmation input]"
                if sensitive
                else (text if reason == "answered" else "[unavailable or unclear input]")
            )
            turn.reply, turn.reason, turn.state = reply, reason, "processed"
            if (
                verification
                and pending_phone(
                    session,
                    org_id=call.org_id,
                    principal_id=call.principal_id,
                    challenge_id=call.phone_challenge_id,
                )
                is None
            ):
                call.state = "closed"
            session.commit()
            return reply
        except Exception:
            session.rollback()
            turn = session.get(VoiceTurn, turn.id)
            turn.state, turn.reason = "unknown", "reconciliation_required"
            reply = self._failure_reply(session, call, index)
            session.commit()
            return reply
