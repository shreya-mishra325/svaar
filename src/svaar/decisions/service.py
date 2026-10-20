"""Ask questions, validate each answer independently, fall back and audit.

A transport-level failure falls back for every question. Within a response, valid
answers are kept and only missing or invalid ones fall back.
"""

import hashlib
import logging
import re
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session

from svaar.config import Settings
from svaar.decisions.fallback import HeuristicEngine
from svaar.decisions.models import DecisionRecord
from svaar.decisions.policy import PolicyOutcome, evaluate, is_valid
from svaar.decisions.questions import Question
from svaar.decisions.types import Decision, DecisionEngine, DecisionUnavailableError

logger = logging.getLogger(__name__)

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{6,}\d")


def redact(state: str) -> str:
    """Remove email addresses and phone numbers; callers must omit names themselves."""
    return _PHONE.sub("[phone]", _EMAIL.sub("[email]", state))


@dataclass(frozen=True)
class PolicyDecision:
    """A decision, its policy outcome and why the fallback was used, if it was."""

    decision: Decision
    outcome: PolicyOutcome
    fallback_reason: str | None


class DecisionService:
    """Run questions through an engine with per-question fallback and audit."""

    def __init__(self, engine: DecisionEngine | None, *, high: float, low: float) -> None:
        self.engine = engine
        self.fallback = HeuristicEngine()
        self.high = high
        self.low = low

    @classmethod
    def from_settings(cls, engine: DecisionEngine | None, settings: Settings) -> "DecisionService":
        """Build a service using the configured policy thresholds."""
        return cls(engine, high=settings.policy_high, low=settings.policy_low)

    def decide(
        self,
        session: Session,
        *,
        org_id: uuid.UUID,
        state: str,
        questions: Sequence[Question],
        incident_id: uuid.UUID | None = None,
    ) -> list[PolicyDecision]:
        """Answer every question and add one audit row each to the caller's transaction."""
        redacted = redact(state)
        answers, transport_failure = self._ask(redacted, questions)
        state_hash = hashlib.sha256(redacted.encode()).hexdigest()
        results = []
        for question in questions:
            decision = answers.get(question.name)
            reason = transport_failure
            if reason is None and decision is None:
                reason = "missing_answer"
            elif reason is None and not is_valid(decision, question):
                reason = "invalid_answer"
            if reason is not None:
                # Fallback labels come from the raw text; it is never sent anywhere.
                decision = self.fallback.answer(state, question)
            outcome = evaluate(decision, question, high=self.high, low=self.low)
            session.add(
                DecisionRecord(
                    org_id=org_id,
                    incident_id=incident_id,
                    state_hash=state_hash,
                    question=question.name,
                    answer=decision.value,
                    confidence=decision.confidence,
                    probabilities=dict(decision.probabilities) or None,
                    model_version=decision.model_version,
                    source=decision.source.value,
                    fallback_reason=reason,
                    policy_outcome=outcome.value,
                )
            )
            results.append(PolicyDecision(decision, outcome, reason))
        session.flush()
        return results

    def _ask(
        self, state: str, questions: Sequence[Question]
    ) -> tuple[dict[str, Decision], str | None]:
        """Call the engine; return answers by name and a transport failure reason."""
        if self.engine is None:
            return {}, "engine_not_configured"
        try:
            answers = list(self.engine.decide(state, questions))
        except DecisionUnavailableError:
            return {}, "engine_unavailable"
        except Exception as exc:
            logger.error("decision_engine_failed", extra={"error_type": type(exc).__name__})
            return {}, "engine_unavailable"
        counts = Counter(answer.name for answer in answers)
        # Duplicate answers for one question are ambiguous, so neither is trusted.
        return {a.name: a for a in answers if counts[a.name] == 1}, None
