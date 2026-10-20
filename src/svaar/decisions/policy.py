"""Confidence policy and answer validation.

Confidence chooses between acting, asking and deferring. It never grants
authorization, changes a risk tier or bypasses the dispatcher.
"""

import math
from enum import StrEnum

from svaar.decisions.questions import Question
from svaar.decisions.types import Decision, DecisionSource


class PolicyOutcome(StrEnum):
    """What the caller should do with a decision."""

    ACT = "act"
    ASK = "ask"
    DEFER = "defer"


def evaluate(decision: Decision, question: Question, *, high: float, low: float) -> PolicyOutcome:
    """Map a validated decision to an outcome.

    Fallback answers always defer. Confidence at or above ``high`` acts only for
    reversible questions; below ``low`` defers; anything else asks.
    """
    if decision.source is DecisionSource.FALLBACK or decision.confidence < low:
        return PolicyOutcome.DEFER
    if decision.confidence >= high and question.reversible:
        return PolicyOutcome.ACT
    return PolicyOutcome.ASK


def is_valid(decision: Decision, question: Question) -> bool:
    """Check label, confidence range and probability fields against the question."""
    if decision.name != question.name or decision.value not in question.labels:
        return False
    if not _unit_interval(decision.confidence):
        return False
    return all(
        label in question.labels and _unit_interval(probability)
        for label, probability in decision.probabilities.items()
    )


def _unit_interval(value: object) -> bool:
    """Return whether value is a real number in [0, 1]."""
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0.0 <= value <= 1.0
    )
