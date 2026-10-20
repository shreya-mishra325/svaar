"""Invites are single-use and expiring; only authenticated senders get verified bindings."""

import threading
import uuid
from datetime import timedelta

import pytest
from factories import make_org, make_principal
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from svaar.identity import service
from svaar.identity.models import ChannelBinding, Invite, Principal, Role

pytestmark = pytest.mark.postgres
TTL = timedelta(hours=1)


def redeem(session: Session, code: str, address: str = "user-1", **overrides: object) -> Principal:
    arguments = {
        "code": code,
        "channel": "telegram",
        "address": address,
        "display_name": "Asha",
        "sender_authenticated": True,
    }
    arguments.update(overrides)
    return service.redeem_invite(session, **arguments)


def test_invite_code_format_and_normalization() -> None:
    code = service.generate_invite_code()
    assert len(code) == 14 and code.count("-") == 2
    assert not set(code.replace("-", "")) & set("01OIL")
    assert service.hash_invite_code(code) == service.hash_invite_code(f" {code.lower()} ")


def test_redemption_creates_principal_with_verified_binding(db_session: Session) -> None:
    org = make_org(db_session)
    issued = service.create_invite(db_session, org.id, Role.LEAD, TTL)
    db_session.commit()
    assert issued.invite.code_hash != issued.code

    principal = redeem(db_session, issued.code.replace("-", " ").lower())
    db_session.commit()

    assert (principal.org_id, principal.role) == (org.id, "lead")
    assert service.resolve_principal(db_session, "telegram", "user-1").id == principal.id
    db_session.refresh(issued.invite)
    assert issued.invite.used_at is not None
    assert issued.invite.used_by_principal_id == principal.id


def test_invite_is_single_use(db_session: Session) -> None:
    issued = service.create_invite(db_session, make_org(db_session).id, Role.DEV, TTL)
    redeem(db_session, issued.code)
    db_session.commit()
    with pytest.raises(service.InviteRejectedError):
        redeem(db_session, issued.code, address="user-2")


def test_expired_and_unknown_invites_are_rejected(db_session: Session) -> None:
    issued = service.create_invite(db_session, make_org(db_session).id, Role.DEV, TTL)
    db_session.execute(update(Invite).values(expires_at=func.now() - timedelta(seconds=1)))
    with pytest.raises(service.InviteRejectedError):
        redeem(db_session, issued.code)
    with pytest.raises(service.InviteRejectedError):
        redeem(db_session, "AAAA-BBBB-CCCC")


def test_unauthenticated_sender_never_consumes_or_binds(db_session: Session) -> None:
    issued = service.create_invite(db_session, make_org(db_session).id, Role.DEV, TTL)
    with pytest.raises(service.UnauthenticatedSenderError):
        redeem(db_session, issued.code, sender_authenticated=False)
    assert db_session.scalar(select(func.count()).select_from(ChannelBinding)) == 0
    db_session.refresh(issued.invite)
    assert issued.invite.used_at is None


def test_bound_address_cannot_enroll_again(db_session: Session) -> None:
    org = make_org(db_session)
    make_principal(db_session, org, bindings=(("telegram", "user-1"),))
    issued = service.create_invite(db_session, org.id, Role.ADMIN, TTL)
    with pytest.raises(service.AddressAlreadyBoundError):
        redeem(db_session, issued.code)


def test_concurrent_redemption_creates_one_principal(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        issued = service.create_invite(session, make_org(session).id, Role.DEV, TTL)
        session.commit()
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def attempt(address: str) -> None:
        with session_factory() as session:
            barrier.wait()
            try:
                redeem(session, issued.code, address=address)
                session.commit()
                outcomes.append("ok")
            except service.InviteRejectedError:
                session.rollback()
                outcomes.append("rejected")

    threads = [threading.Thread(target=attempt, args=(f"user-{i}",)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["ok", "rejected"]
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Principal)) == 1


def test_unverified_binding_does_not_resolve(db_session: Session) -> None:
    make_principal(db_session, make_org(db_session), bindings=(("phone", "+1"),), verified=False)
    assert service.resolve_principal(db_session, "phone", "+1") is None


def test_principal_lookup_is_org_scoped(db_session: Session) -> None:
    principal = make_principal(db_session, make_org(db_session))
    other = make_org(db_session, "Other")
    assert service.get_principal(db_session, principal.org_id, principal.id) is not None
    assert service.get_principal(db_session, other.id, principal.id) is None


def test_invite_requires_existing_org(db_session: Session) -> None:
    with pytest.raises(service.IdentityError):
        service.create_invite(db_session, uuid.uuid4(), Role.DEV, TTL)
