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

CLAIM_DETECTION = Question(
    name="claim_detection",
    labels=("claim", "no_claim"),
    criteria={
        "claim": (
            "States that specific engineering work is done or in a given state, "
            "such as a fix merged, a build passing or a deploy finished"
        ),
        "no_claim": "A question, request, plan, opinion or anything else without such a status",
    },
    fallback="no_claim",
    reversible=True,
)

P0_QUESTIONS = (VOICE_INTENT, TRANSCRIPT_USABILITY, CLAIM_ANSWER)
CI_FAILURE_CATEGORY = Question(
    name="ci_failure_category",
    labels=("flaky", "test", "dependency", "infra", "config", "unknown"),
    criteria={
        "flaky": "Intermittent failure likely to pass on retry without a code change",
        "test": "A test assertion or test suite failure caused by the change",
        "dependency": "A package, image or external dependency problem",
        "infra": "Runner, network, quota or other infrastructure problem",
        "config": "Workflow, secret or configuration error",
        "unknown": "Not enough information to tell",
    },
    fallback="unknown",
    reversible=True,
)

# Advice can only delay escalation once; deterministic timing and limits still apply.
ESCALATION_STEP = Question(
    name="escalation_step",
    labels=("wait", "chat_nudge", "call_now"),
    criteria={
        "wait": "Waiting a little longer is reasonable before calling",
        "chat_nudge": "A chat reminder should come before a call",
        "call_now": "Calling the owner now is appropriate",
    },
    fallback="call_now",
    reversible=True,
)

P1_QUESTIONS = (CLAIM_DETECTION, CI_FAILURE_CATEGORY, ESCALATION_STEP)
