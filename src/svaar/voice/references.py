"""Internal call-reference resolution; not a verified Bolna request contract.

An authenticated transport must supply both the private placement reference and
a stable zero-based turn index. No HTTP route or model-derived index is provided.
"""

import hashlib
import re

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from svaar.voice.contracts import TurnRunner
from svaar.voice.models import VoiceCall
from svaar.voice.runtime import REFUSAL


class ReferencedTurnRunner:
    """Resolve hashed private locators without accepting asserted caller identities."""

    def __init__(self, sessions: sessionmaker[Session], runner: TurnRunner) -> None:
        self.sessions = sessions
        self.runner = runner

    def run_turn(self, reference: str, text: str, *, turn_index: int | None = None) -> str:
        """Resolve a placed call then delegate authorization and durable turn dedupe."""
        if (
            not isinstance(reference, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{43,128}", reference) is None
            or type(turn_index) is not int
            or not 0 <= turn_index <= 2147483647
            or not isinstance(text, str)
            or not text.strip()
            or len(text) > 20000
        ):
            return REFUSAL
        digest = hashlib.sha256(reference.encode()).hexdigest()
        with self.sessions() as session:
            identifier = session.scalar(
                select(VoiceCall.id).where(
                    VoiceCall.call_ref_hash == digest,
                    VoiceCall.execution_id.is_not(None),
                    VoiceCall.provider_agent_id.is_not(None),
                    VoiceCall.state.in_(("active", "closed")),
                )
            )
        if identifier is None:
            return REFUSAL
        # The shared runner rechecks call state, mission and current identity.
        # Closed calls permit only already-processed retries, never a new turn.
        return self.runner.run_turn(str(identifier), text, turn_index=turn_index)
