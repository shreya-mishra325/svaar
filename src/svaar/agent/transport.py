"""Provider-independent chat transport contracts; no business handlers live here."""

from dataclasses import dataclass
from typing import Protocol


class TransportUnavailableError(Exception):
    """A read failed; no provider body or credential is exposed."""


class DeliveryRejectedError(Exception):
    """The provider rejected a send; retryable requires known non-acceptance."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class DeliveryUncertainError(Exception):
    """Delivery may have started; do not blindly send again."""


@dataclass(frozen=True, repr=False)
class InboundMessage:
    """Untrusted caller text plus transport IDs, never safe for logging."""

    channel: str
    connection_id: str
    external_message_id: str
    thread_id: str
    sender_address: str
    text: str
    sender_authenticated: bool = False


@dataclass(frozen=True, repr=False)
class PollBatch:
    """Persist messages and next_cursor together before advancing the next poll."""

    messages: tuple[InboundMessage, ...]
    next_cursor: int


@dataclass(frozen=True, repr=False)
class DeliveryReceipt:
    """Provider acceptance is queued, not proof of delivery to the recipient."""

    delivery_id: str
    status: str


class ChannelTransport(Protocol):
    """Replaceable synchronous polling and delivery boundary."""

    def poll(self, *, after_seq: int, limit: int = 100) -> PollBatch:
        """Read events without advancing durable local state."""
        ...

    def send(self, target: InboundMessage, text: str) -> DeliveryReceipt:
        """Reply through a trusted outbox caller, never from a model directly."""
        ...

    def close(self) -> None:
        """Release owned connections."""
        ...
