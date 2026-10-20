"""Deterministic heuristic fallback used when Jev is unavailable or invalid.

Fallback answers carry confidence 0.0 and source ``fallback``, so the policy layer
always defers them; they can never authorize or create evidence on their own.
"""

import re
from collections.abc import Sequence

from svaar.decisions.questions import TRANSCRIPT_USABILITY, VOICE_INTENT, Question
from svaar.decisions.types import Decision, DecisionSource

_INTENT_PATTERNS = (
    ("confirm_action", re.compile(r"\b(confirm|code)\b|(\d\D?){6}")),
    ("explain_failure", re.compile(r"\b(why|fail(ed|ing|ure)?|broke|error)\b")),
    ("verify_claim", re.compile(r"\b(merged|fixed|done|shipped|deployed)\b")),
    ("investigate", re.compile(r"\b(what happened|timeline|status|incident)\b")),
)


class HeuristicEngine:
    """Keyword and length rules; answers every question it is given."""

    def decide(self, state: str, questions: Sequence[Question]) -> Sequence[Decision]:
        """Answer each question deterministically from ``state``."""
        return [self.answer(state, question) for question in questions]

    def answer(self, state: str, question: Question) -> Decision:
        """Return a fallback decision for one question."""
        return Decision(
            name=question.name,
            value=_label(state, question),
            confidence=0.0,
            source=DecisionSource.FALLBACK,
        )


def _label(state: str, question: Question) -> str:
    """Pick a label; questions without rules use their safe fallback label."""
    text = state.strip().lower()
    if question.name == TRANSCRIPT_USABILITY.name:
        if not any(ch.isalnum() for ch in text):
            return "unusable"
        return "repeat" if len(text.split()) < 2 else "usable"
    if question.name == VOICE_INTENT.name:
        for label, pattern in _INTENT_PATTERNS:
            if pattern.search(text):
                return label
    return question.fallback
