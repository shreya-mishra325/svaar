"""Phone ownership challenges; issuance is internal until private chat delivery is wired."""

import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from svaar.identity.models import ChannelBinding, PhoneChallenge, Principal
from svaar.identity.service import IdentityError, find_binding, get_principal, verified_channels

MAX_ATTEMPTS = 3
CHALLENGE_TTL = timedelta(minutes=10)
RESEND_DELAY = timedelta(minutes=1)


@dataclass(frozen=True)
class IssuedPhoneChallenge:
    """Plaintext code returned once to a trusted private-chat delivery coordinator."""

    challenge_id: uuid.UUID
    code: str = field(repr=False)


def _phone_lock(session: Session, phone: str) -> None:
    """Serialize address ownership changes without reserving an unverified binding."""
    key = int.from_bytes(
        hashlib.sha256(("phone:" + phone).encode()).digest()[:8], "big", signed=True
    )
    session.execute(sql_text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def _digest(code: str, salt: str) -> str:
    """Use a salted memory-hard hash for a low-entropy spoken code."""
    return hashlib.scrypt(code.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()


def issue_phone_challenge(
    session: Session,
    *,
    org_id: uuid.UUID,
    principal_id: uuid.UUID,
    phone: str,
) -> IssuedPhoneChallenge:
    """Issue for an enrolled caller only; caller commits and privately delivers the code.

    Cooldown is one minute per principal and target number. Existing pending
    challenges for this principal are canceled. No phone binding is created yet.
    """
    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", phone):
        raise IdentityError("Use an E.164 phone number")
    principal = session.scalar(
        select(Principal)
        .where(Principal.id == principal_id, Principal.org_id == org_id)
        .with_for_update()
    )
    if principal is None or not any(
        ch != "phone" for ch in verified_channels(session, principal_id)
    ):
        raise IdentityError("A verified chat identity is required")
    _phone_lock(session, phone)
    binding = find_binding(session, "phone", phone)
    if binding is not None and (
        binding.principal_id != principal_id or binding.verified_at is not None
    ):
        raise IdentityError("Phone verification is unavailable")
    now = datetime.now(UTC)
    recent = session.scalar(
        select(PhoneChallenge.id)
        .where(
            (
                (PhoneChallenge.principal_id == principal_id)
                | (PhoneChallenge.phone_number == phone)
            ),
            PhoneChallenge.created_at > now - RESEND_DELAY,
        )
        .limit(1)
    )
    if recent is not None:
        raise IdentityError("Wait before requesting another phone verification")
    session.execute(
        update(PhoneChallenge)
        .where(PhoneChallenge.principal_id == principal_id, PhoneChallenge.state == "pending")
        .values(state="canceled")
    )
    code = f"{secrets.randbelow(1000000):06d}"
    salt = secrets.token_hex(16)
    challenge = PhoneChallenge(
        org_id=org_id,
        principal_id=principal_id,
        phone_number=phone,
        code_hash=_digest(code, salt),
        code_salt=salt,
        expires_at=now + CHALLENGE_TTL,
    )
    session.add(challenge)
    session.flush()
    return IssuedPhoneChallenge(challenge.id, code)


def pending_phone(
    session: Session,
    *,
    org_id: uuid.UUID,
    principal_id: uuid.UUID,
    challenge_id: uuid.UUID | None,
) -> str | None:
    """Resolve only an unexpired, intended challenge; never grants ordinary phone trust."""
    if challenge_id is None or get_principal(session, org_id, principal_id) is None:
        return None
    challenge = session.scalar(
        select(PhoneChallenge)
        .where(
            PhoneChallenge.id == challenge_id,
            PhoneChallenge.org_id == org_id,
            PhoneChallenge.principal_id == principal_id,
            PhoneChallenge.state == "pending",
            PhoneChallenge.attempts < MAX_ATTEMPTS,
            PhoneChallenge.expires_at > datetime.now(UTC),
        )
        .execution_options(populate_existing=True)
    )
    if challenge is None:
        return None
    binding = find_binding(session, "phone", challenge.phone_number)
    if binding is not None and (
        binding.principal_id != principal_id or binding.verified_at is not None
    ):
        return None
    return challenge.phone_number


def verify_phone_challenge(
    session: Session,
    *,
    org_id: uuid.UUID,
    principal_id: uuid.UUID,
    challenge_id: uuid.UUID | None,
    spoken: str,
) -> dict[str, object]:
    """Compare exact ASCII digits after removing spaces/hyphens, under ownership locks.

    No word-to-digit guessing, substring extraction or model-selected code is
    accepted. Every mismatch consumes an attempt; callers own the transaction.
    """
    if challenge_id is None:
        return {"verified": False, "reason": "challenge_unavailable"}
    snapshot = session.scalar(
        select(PhoneChallenge).where(
            PhoneChallenge.id == challenge_id,
            PhoneChallenge.org_id == org_id,
            PhoneChallenge.principal_id == principal_id,
        )
    )
    if snapshot is None:
        return {"verified": False, "reason": "challenge_unavailable"}
    _phone_lock(session, snapshot.phone_number)
    challenge = session.scalar(
        select(PhoneChallenge)
        .where(PhoneChallenge.id == challenge_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if challenge.state != "pending":
        return {"verified": False, "reason": "challenge_unavailable"}
    now = datetime.now(UTC)
    if challenge.expires_at <= now:
        challenge.state = "expired"
        return {"verified": False, "reason": "expired"}
    if (
        pending_phone(session, org_id=org_id, principal_id=principal_id, challenge_id=challenge_id)
        is None
    ):
        return {"verified": False, "reason": "challenge_unavailable"}
    digits = re.sub(r"[\s-]", "", spoken)
    valid = bool(re.fullmatch(r"[0-9]{6}", digits))
    challenge.attempts += 1
    if not valid or not hmac.compare_digest(
        _digest(digits, challenge.code_salt), challenge.code_hash
    ):
        if challenge.attempts >= MAX_ATTEMPTS:
            challenge.state = "locked"
        return {
            "verified": False,
            "reason": "locked" if challenge.state == "locked" else "code_mismatch",
        }
    binding = find_binding(session, "phone", challenge.phone_number)
    if binding is None:
        binding = ChannelBinding(
            principal_id=principal_id, channel="phone", address=challenge.phone_number
        )
        session.add(binding)
    binding.verified_at = now
    challenge.state = "verified"
    session.flush()
    return {"verified": True, "reason": "verified"}


def phone_challenge_state(
    session: Session,
    *,
    org_id: uuid.UUID,
    principal_id: uuid.UUID,
    challenge_id: uuid.UUID | None,
) -> str | None:
    """Expose scoped status without exposing the number, hash or code."""
    return session.scalar(
        select(PhoneChallenge.state).where(
            PhoneChallenge.id == challenge_id,
            PhoneChallenge.org_id == org_id,
            PhoneChallenge.principal_id == principal_id,
        )
    )
