"""Replaceable outbound voice provider contract; no provider requests on import."""

import uuid
from dataclasses import dataclass
from typing import Protocol

TERMINAL_STATUSES = frozenset(
    {"completed", "no-answer", "busy", "failed", "canceled", "stopped", "error", "balance-low"}
)
PROGRESS_STATUSES = (
    "scheduled",
    "rescheduled",
    "queued",
    "initiated",
    "ringing",
    "in-progress",
    "call-disconnected",
)


class VoiceProviderUnavailableError(Exception):
    """A read-only provider request could not be verified."""


class CallRejectedError(Exception):
    """Provider explicitly rejected placement; no automatic redial is authorized."""


class CallOutcomeUnknownError(Exception):
    """A provider may have accepted placement; never blindly retry."""


@dataclass(frozen=True)
class CallReceipt:
    """Provider acceptance only, not proof that the recipient answered."""

    execution_id: uuid.UUID


@dataclass(frozen=True)
class ExecutionStatus:
    """Minimal verified execution identity/status; no transcript or phone payload."""

    execution_id: uuid.UUID
    agent_id: uuid.UUID
    status: str


class VoiceProvider(Protocol):
    """Placement and read-only reconciliation for a single configured agent."""

    agent_id: uuid.UUID

    def place_call(self, phone: str, call_ref: str) -> CallReceipt:
        """Place one outbound call; the caller must persist intent before invoking."""
        ...

    def execution(self, execution_id: uuid.UUID) -> ExecutionStatus:
        """Read and validate a previously accepted execution."""
        ...

    def close(self) -> None:
        """Release provider resources."""
        ...
