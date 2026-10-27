"""Provider-independent decision interface shared by structured classifiers and the fallback."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from svaar.decisions.questions import Question


class DecisionSource(StrEnum):
    """Where an answer came from."""

    MODEL = "model"
    FALLBACK = "fallback"


@dataclass(frozen=True)
class Decision:
    """A typed answer to one named question.

    Attributes:
        name: The question name the answer belongs to.
        value: The chosen label.
        confidence: Confidence in the range 0.0 to 1.0. Fallback answers use 0.0;
            a missing provider confidence is never invented.
        probabilities: Per-label probabilities when the provider returns them.
        model_version: Pinned model version, or ``heuristic`` for the fallback.
        source: Whether a model or the fallback produced the answer.
    """

    name: str
    value: str
    confidence: float
    probabilities: Mapping[str, float] = field(default_factory=dict)
    model_version: str = "heuristic"
    source: DecisionSource = DecisionSource.MODEL


class DecisionUnavailableError(Exception):
    """The engine could not answer within its timeout or returned an invalid response."""


class DecisionEngine(Protocol):
    """Interface implemented by structured classifiers and the heuristic fallback."""

    def decide(self, state: str, questions: Sequence[Question]) -> Sequence[Decision]:
        """Answer typed questions about a redacted state.

        Args:
            state: Description of the situation, with personal data redacted.
            questions: Named typed questions.

        Returns:
            Decisions for the questions it could answer. Missing or invalid answers
            are replaced by the fallback per question by the caller.

        Raises:
            DecisionUnavailableError: On timeout, transport failure or a response
                that cannot be parsed at all.
        """
        ...
