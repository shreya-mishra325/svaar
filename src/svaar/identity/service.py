"""Organization-scoped identity operations; callers own the transaction.

Identity comes from authenticated transports and verified challenges only. Nothing
here trusts an asserted email, a model-proposed identity or an organization guess.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from svaar.identity.models import ChannelBinding, Invite, Org, Principal, Role

# Excludes 0/O and 1/I/L so codes survive being read or typed by hand.
INVITE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
INVITE_GROUPS = 3
INVITE_GROUP_LENGTH = 4


class IdentityError(Exception):
    """Base class for refused identity operations; messages are safe to show."""


class InviteRejectedError(IdentityError):
    """The code is unknown, expired or already used; the reason is not disclosed."""


class UnauthenticatedSenderError(IdentityError):
    """The transport could not authenticate the sender, so no binding is created."""


class AddressAlreadyBoundError(IdentityError):
    """The channel address already belongs to a principal."""


@dataclass(frozen=True)
class IssuedInvite:
    """An invite row plus its plaintext code, which is returned exactly once."""

    invite: Invite
    code: str


def normalize_invite_code(code: str) -> str:
    """Canonicalize user input: uppercase, separators and whitespace removed."""
    return "".join(ch for ch in code.upper() if ch.isalnum())


def hash_invite_code(code: str) -> str:
    """Hash a normalized code; codes carry about 59 bits so no salt is needed."""
    return hashlib.sha256(normalize_invite_code(code).encode()).hexdigest()


def generate_invite_code() -> str:
    """Return a grouped, unambiguous random code such as ``K7QM-2XPA-9RTD``."""
    groups = (
        "".join(secrets.choice(INVITE_ALPHABET) for _ in range(INVITE_GROUP_LENGTH))
        for _ in range(INVITE_GROUPS)
    )
    return "-".join(groups)


def create_org(session: Session, name: str) -> Org:
    """Create an organization; only operator routes may call this."""
    org = Org(name=name)
    session.add(org)
    session.flush()
    return org


def get_org(session: Session, org_id: uuid.UUID) -> Org | None:
    """Return an organization by ID."""
    return session.get(Org, org_id)


def create_invite(session: Session, org_id: uuid.UUID, role: Role, ttl: timedelta) -> IssuedInvite:
    """Issue a single-use invite for an existing organization.

    Raises:
        IdentityError: If the organization does not exist.
    """
    if session.get(Org, org_id) is None:
        raise IdentityError("Organization not found")
    code = generate_invite_code()
    invite = Invite(
        org_id=org_id,
        role=role.value,
        code_hash=hash_invite_code(code),
        expires_at=datetime.now(UTC) + ttl,
    )
    session.add(invite)
    session.flush()
    return IssuedInvite(invite=invite, code=code)


def redeem_invite(
    session: Session,
    *,
    code: str,
    channel: str,
    address: str,
    display_name: str,
    sender_authenticated: bool,
) -> Principal:
    """Consume an invite and create a principal with a verified channel binding.

    The invite is consumed by one conditional update, so concurrent redemptions
    of the same code produce at most one principal. The caller commits; on any
    error the caller must roll back, which also restores the invite.

    Raises:
        UnauthenticatedSenderError: If the transport did not authenticate the sender.
        AddressAlreadyBoundError: If the address is already bound.
        InviteRejectedError: If the code is unknown, expired or already used.
    """
    if not sender_authenticated:
        raise UnauthenticatedSenderError("This channel cannot verify who you are")
    if find_binding(session, channel, address) is not None:
        raise AddressAlreadyBoundError("This address is already enrolled")

    now = datetime.now(UTC)
    claimed = session.execute(
        update(Invite)
        .where(
            Invite.code_hash == hash_invite_code(code),
            Invite.used_at.is_(None),
            Invite.expires_at > func.now(),
        )
        .values(used_at=now)
        .returning(Invite.id, Invite.org_id, Invite.role)
    ).one_or_none()
    if claimed is None:
        raise InviteRejectedError("That invite code is not valid")

    principal = Principal(org_id=claimed.org_id, role=claimed.role, display_name=display_name)
    session.add(principal)
    session.flush()
    session.add(
        ChannelBinding(principal_id=principal.id, channel=channel, address=address, verified_at=now)
    )
    session.execute(
        update(Invite).where(Invite.id == claimed.id).values(used_by_principal_id=principal.id)
    )
    session.flush()
    return principal


def find_binding(session: Session, channel: str, address: str) -> ChannelBinding | None:
    """Return the binding for an address, verified or not."""
    return session.scalars(
        select(ChannelBinding).where(
            ChannelBinding.channel == channel, ChannelBinding.address == address
        )
    ).one_or_none()


def resolve_principal(session: Session, channel: str, address: str) -> Principal | None:
    """Return the principal behind a verified binding; unverified bindings resolve to None."""
    return session.scalars(
        select(Principal)
        .join(ChannelBinding, ChannelBinding.principal_id == Principal.id)
        .where(
            ChannelBinding.channel == channel,
            ChannelBinding.address == address,
            ChannelBinding.verified_at.is_not(None),
        )
    ).one_or_none()


def get_principal(session: Session, org_id: uuid.UUID, principal_id: uuid.UUID) -> Principal | None:
    """Return a principal only when it belongs to the given organization."""
    return session.scalars(
        select(Principal).where(Principal.id == principal_id, Principal.org_id == org_id)
    ).one_or_none()


def verified_channels(session: Session, principal_id: uuid.UUID) -> list[str]:
    """Return the channels on which the principal holds a verified binding."""
    return list(
        session.scalars(
            select(ChannelBinding.channel)
            .where(
                ChannelBinding.principal_id == principal_id,
                ChannelBinding.verified_at.is_not(None),
            )
            .order_by(ChannelBinding.channel)
        )
    )
