"""Fixed chat and voice execution budgets from the product plan."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TurnProfile:
    """Limits enforced before model requests and before dispatching tool calls."""

    rounds: int
    calls_per_round: int
    deadline_seconds: float
    http_timeout_seconds: float
    retries: int


CHAT = TurnProfile(4, 4, 45.0, 30.0, 1)
VOICE = TurnProfile(2, 2, 8.0, 6.0, 0)
