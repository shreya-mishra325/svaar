"""Typed decision slots. Keep the runtime catalogue small; schemas live only here.

Each slot has fixed allowed outputs, a deterministic fallback label and a
reversibility flag the policy layer uses. The mission guard is deterministic code
in ``actions.missions``, not a decision slot.
"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Question:
    """A named ``choice`` question.

    Attributes:
        name: Stable slot name used in requests and audit rows.
        labels: Allowed outputs; anything else is invalid.
        criteria: Per-label criteria sent to the decision model.
        fallback: Safe label used when the engine is unavailable or invalid.
        reversible: Whether acting on a confident answer can be undone.
        kind: Question type; only ``choice`` is used by P0 slots.
    """

    name: str
    labels: tuple[str, ...]
    criteria: dict[str, str]
    fallback: str
    reversible: bool
    kind: Literal["choice"] = "choice"

    def __post_init__(self) -> None:
        if self.fallback not in self.labels or set(self.criteria) != set(self.labels):
            raise ValueError(f"Inconsistent question definition: {self.name}")


VOICE_INTENT = Question(
    name="voice_intent",
    labels=(
        "investigate",
        "verify_claim",
        "explain_failure",
        "propose_resolution",
        "confirm_action",
        "other",
    ),
    criteria={
        "investigate": "Asks what happened, the incident status or the timeline",
        "verify_claim": "Asks whether a status claim is true or provides an answer about one",
        "explain_failure": "Asks why a CI run or deploy failed",
        "propose_resolution": "Proposes or asks for a fix, plan or exception",
        "confirm_action": "Reads out a confirmation code or asks to confirm a pending action",
        "other": "Anything else, unrelated or unclear",
    },
    fallback="other",
    reversible=True,
)

TRANSCRIPT_USABILITY = Question(
    name="transcript_usability",
    labels=("usable", "repeat", "clarify", "unusable"),
    criteria={
        "usable": "Intelligible and complete enough to interpret",
        "repeat": "Partly heard or cut off; asking to repeat would help",
        "clarify": "Heard clearly but ambiguous in meaning",
        "unusable": "Noise, silence or unintelligible speech",
    },
    fallback="repeat",
    reversible=True,
)

CLAIM_ANSWER = Question(
    name="claim_answer",
    labels=("confirmed", "denied", "unsure", "wrong_person", "callback"),
    criteria={
        "confirmed": "The person clearly states the claimed work is done",
        "denied": "The person clearly states the claimed work is not done",
        "unsure": "The person does not know or gives no clear answer",
        "wrong_person": "The person says they are not the right contact",
        "callback": "The person asks to be called back later",
    },
    fallback="unsure",
    reversible=False,
)

P0_QUESTIONS = (VOICE_INTENT, TRANSCRIPT_USABILITY, CLAIM_ANSWER)
