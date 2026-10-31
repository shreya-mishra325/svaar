"""Call-reference resolution for the authenticated Bolna turn routes.

The transport supplies the private placement reference and, in llm_endpoint mode,
a stable zero-based index derived from replayed history. Function mode has no
provider retry identity, so run_next sequences arrivals (A-028).
"""

import hashlib
import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from svaar.voice.contracts import TurnRunner
from svaar.voice.models import VoiceCall, VoiceTurn
from svaar.voice.runtime import REFUSAL


class ReferencedTurnRunner:
    """Resolve hashed private locators without accepting asserted caller identities."""

    def __init__(self, sessions: sessionmaker[Session], runner: TurnRunner) -> None:
        self.sessions = sessions
        self.runner = runner

    def _resolve(self, reference: object) -> uuid.UUID | None:
        """Find a placed call by reference hash; an authenticated turn activates it.

        A queued call already has a provider receipt, and a turn proves the call is
        connected even when the in-progress status callback has not arrived.
        """
        if (
            not isinstance(reference, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{43,128}", reference) is None
        ):
            return None
        digest = hashlib.sha256(reference.encode()).hexdigest()
        with self.sessions() as session:
            call = session.scalar(
                select(VoiceCall)
                .where(
                    VoiceCall.call_ref_hash == digest,
                    VoiceCall.execution_id.is_not(None),
                    VoiceCall.provider_agent_id.is_not(None),
                    VoiceCall.state.in_(("queued", "active", "closed")),
                )
                .with_for_update()
            )
            if call is None:
                return None
            if call.state == "queued":
                call.state = "active"
                session.commit()
            return call.id

    def run_turn(self, reference: str, text: str, *, turn_index: int | None = None) -> str:
        """Resolve a placed call then delegate authorization and durable turn dedupe."""
        if (
            type(turn_index) is not int
            or not 0 <= turn_index <= 2147483647
            or not isinstance(text, str)
            or not text.strip()
            or len(text) > 20000
        ):
            return REFUSAL
        identifier = self._resolve(reference)
        if identifier is None:
            return REFUSAL
        # The shared runner rechecks call state, mission and current identity.
        # Closed calls permit only already-processed retries, never a new turn.
        return self.runner.run_turn(str(identifier), text, turn_index=turn_index)

    def run_next(self, reference: str, text: str) -> str:
        """Function mode: give each authenticated arrival the next index.

        Bolna's function bridge carries no retry identifier, so a provider-side
        retry of the same utterance would run as a new turn (A-028).
        """
        if not isinstance(text, str) or not text.strip() or len(text) > 20000:
            return REFUSAL
        identifier = self._resolve(reference)
        if identifier is None:
            return REFUSAL
        with self.sessions() as session:
            latest = session.scalar(
                select(func.max(VoiceTurn.turn_index)).where(VoiceTurn.voice_call_id == identifier)
            )
        index = 0 if latest is None else latest + 1
        return self.runner.run_turn(str(identifier), text, turn_index=index)
