"""Owner-bound, expiring, single-use confirmations for tier-2 actions.

The nonce is compared exactly in code after canonicalization; a model's "yes" is
never a confirmation. The ``pending`` to ``confirmed`` transition is one
conditional update, so concurrent attempts have at most one winner.
"""

import hashlib
import hmac
import json
import secrets
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from svaar.approvals.models import Confirmation, ConfirmationState

NONCE_LENGTH = 6


class ConfirmOutcome(StrEnum):
    """Result of one confirmation attempt."""

    CONFIRMED = "confirmed"
    NO_MATCH = "no_match"
    SAME_CHANNEL = "same_channel"
    LOCKED = "locked"


@dataclass(frozen=True)
class IssuedConfirmation:
    """A confirmation row plus its plaintext nonce, for out-of-band delivery only."""

    confirmation: Confirmation
    nonce: str


@dataclass(frozen=True)
class ConfirmResult:
    """Outcome of a confirmation attempt; ``confirmation`` is set only when confirmed."""

    outcome: ConfirmOutcome
    confirmation: Confirmation | None = None


def compute_action_hash(action: str, arguments: Mapping[str, Any]) -> str:
    """Hash an action and its canonical JSON arguments."""
    canonical = json.dumps({"action": action, "arguments": arguments}, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def normalize_nonce(text: str) -> str:
    """Keep digits only, so "4 8-1 5 1 6" and "481516" compare equal."""
    return "".join(ch for ch in text if ch.isdigit())


def _hash_nonce(confirmation_id: uuid.UUID, nonce: str) -> str:
    """Salt with the confirmation ID so equal nonces never share a hash."""
    return hashlib.sha256(f"{confirmation_id}:{normalize_nonce(nonce)}".encode()).hexdigest()


def create_confirmation(
    session: Session,
    *,
    org_id: uuid.UUID,
    principal_id: uuid.UUID,
    action: str,
    arguments: Mapping[str, Any],
    requested_channel: str,
    ttl: timedelta,
) -> IssuedConfirmation:
    """Create a pending confirmation with a fresh numeric nonce.

    Digits are used because speech-to-text transcribes them most reliably.
    """
    nonce = "".join(secrets.choice("0123456789") for _ in range(NONCE_LENGTH))
    confirmation_id = uuid.uuid4()
    confirmation = Confirmation(
        id=confirmation_id,
        org_id=org_id,
        principal_id=principal_id,
        action=action,
        arguments=dict(arguments),
        action_hash=compute_action_hash(action, arguments),
        nonce_hash=_hash_nonce(confirmation_id, nonce),
        requested_channel=requested_channel,
        state=ConfirmationState.PENDING.value,
        failed_attempts=0,
        expires_at=datetime.now(UTC) + ttl,
    )
    session.add(confirmation)
    session.flush()
    return IssuedConfirmation(confirmation=confirmation, nonce=nonce)


def confirm(
    session: Session,
    *,
    principal_id: uuid.UUID,
    text: str,
    channel: str,
    allow_same_channel: bool,
    max_attempts: int,
) -> ConfirmResult:
    """Confirm the owner's pending confirmation whose nonce matches ``text`` exactly.

    Only confirmations owned by ``principal_id`` are considered. A mismatch counts
    against every pending confirmation of that owner and locks them at the limit.
    The caller commits the returned state.
    """
    candidate = normalize_nonce(text)
    pending = session.scalars(
        select(Confirmation).where(
            Confirmation.principal_id == principal_id,
            Confirmation.state == ConfirmationState.PENDING.value,
            Confirmation.expires_at > func.now(),
        )
    ).all()
    match = next(
        (
            row
            for row in pending
            if len(candidate) == NONCE_LENGTH
            and hmac.compare_digest(row.nonce_hash, _hash_nonce(row.id, candidate))
        ),
        None,
    )
    if match is None:
        return _record_failed_attempt(session, principal_id, max_attempts)
    if match.requested_channel == channel and not allow_same_channel:
        return ConfirmResult(ConfirmOutcome.SAME_CHANNEL)

    claimed = session.execute(
        update(Confirmation)
        .where(
            Confirmation.id == match.id,
            Confirmation.state == ConfirmationState.PENDING.value,
            Confirmation.expires_at > func.now(),
        )
        .values(
            state=ConfirmationState.CONFIRMED.value,
            resolved_at=func.now(),
            resolved_channel=channel,
        )
        .returning(Confirmation.id)
    ).one_or_none()
    if claimed is None:
        return ConfirmResult(ConfirmOutcome.NO_MATCH)
    session.refresh(match)
    return ConfirmResult(ConfirmOutcome.CONFIRMED, match)


def _record_failed_attempt(
    session: Session, principal_id: uuid.UUID, max_attempts: int
) -> ConfirmResult:
    """Count a wrong nonce and lock pending confirmations that reach the limit."""
    session.execute(
        update(Confirmation)
        .where(
            Confirmation.principal_id == principal_id,
            Confirmation.state == ConfirmationState.PENDING.value,
        )
        .values(failed_attempts=Confirmation.failed_attempts + 1)
    )
    locked = session.execute(
        update(Confirmation)
        .where(
            Confirmation.principal_id == principal_id,
            Confirmation.state == ConfirmationState.PENDING.value,
            Confirmation.failed_attempts >= max_attempts,
        )
        .values(state=ConfirmationState.LOCKED.value, resolved_at=func.now())
        .returning(Confirmation.id)
    ).all()
    return ConfirmResult(ConfirmOutcome.LOCKED if locked else ConfirmOutcome.NO_MATCH)


def deny(session: Session, *, principal_id: uuid.UUID, confirmation_id: uuid.UUID) -> bool:
    """Deny a pending confirmation owned by ``principal_id``; return whether it changed."""
    denied = session.execute(
        update(Confirmation)
        .where(
            Confirmation.id == confirmation_id,
            Confirmation.principal_id == principal_id,
            Confirmation.state == ConfirmationState.PENDING.value,
        )
        .values(state=ConfirmationState.DENIED.value, resolved_at=func.now())
        .returning(Confirmation.id)
    ).one_or_none()
    return denied is not None


def expire_stale(session: Session) -> int:
    """Mark pending confirmations past their expiry as expired; return the count."""
    expired = session.execute(
        update(Confirmation)
        .where(
            Confirmation.state == ConfirmationState.PENDING.value,
            Confirmation.expires_at <= func.now(),
        )
        .values(state=ConfirmationState.EXPIRED.value, resolved_at=func.now())
        .returning(Confirmation.id)
    ).all()
    return len(expired)
