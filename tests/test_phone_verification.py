"""Phone ownership, exact-code action gates and narrow call exception with no live providers."""

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from factories import make_org, make_principal
from sqlalchemy import func, select
from test_agent_loop import FakeEngine, FakeModel, proposal
from test_voice_calls import Provider
from test_voice_runtime import build

from svaar.actions.catalog import build_registry
from svaar.actions.dispatcher import ApprovalPolicy, Dispatcher
from svaar.actions.missions import Mission
from svaar.actions.models import ToolExecution
from svaar.actions.registry import Channel, ToolContext
from svaar.agent.llm import ModelReply
from svaar.agent.loop import CLARIFY
from svaar.identity.models import ChannelBinding, PhoneChallenge
from svaar.identity.phones import issue_phone_challenge, pending_phone, verify_phone_challenge
from svaar.identity.service import IdentityError, resolve_principal
from svaar.voice.calls import CallService, create_phone_verification_call
from svaar.voice.models import VoiceCall, VoiceTurn
from svaar.voice.runtime import REFUSAL

PHONE = "+15555550123"


@pytest.fixture
def challenge(session_factory):
    with session_factory() as session:
        org = make_org(session)
        principal = make_principal(session, org, bindings=(("caspian:telegram", "demo-user"),))
        issued = issue_phone_challenge(
            session, org_id=org.id, principal_id=principal.id, phone=PHONE
        )
        session.commit()
        return org.id, principal.id, issued


def verify(session, data, code):
    org, principal, issued = data
    return verify_phone_challenge(
        session, org_id=org, principal_id=principal, challenge_id=issued.challenge_id, spoken=code
    )


def make_call(session_factory, data, active=False):
    org, principal, issued = data
    with session_factory() as session:
        call = create_phone_verification_call(
            session, org_id=org, principal_id=principal, challenge_id=issued.challenge_id
        )
        if active:
            call.state = "active"
        session.commit()
        return call.id


def test_pending_number_never_resolves_as_verified_identity(session_factory, challenge):
    org, principal, issued = challenge
    with session_factory() as session:
        row = session.get(PhoneChallenge, issued.challenge_id)
        assert row.code_hash != issued.code and len(row.code_salt) == 32
        assert issued.code not in repr(issued)
        assert session.scalar(select(func.count()).select_from(ChannelBinding)) == 1
        assert resolve_principal(session, "phone", PHONE) is None
        assert (
            pending_phone(
                session, org_id=org, principal_id=principal, challenge_id=issued.challenge_id
            )
            == PHONE
        )


def test_exact_code_marks_only_intended_number_verified(session_factory, challenge):
    _, principal, issued = challenge
    with session_factory() as session:
        assert verify(session, challenge, " ".join(issued.code)) == {
            "verified": True,
            "reason": "verified",
        }
        session.commit()
        assert resolve_principal(session, "phone", PHONE).id == principal
        assert session.get(PhoneChallenge, issued.challenge_id).attempts == 1
        assert not verify(session, challenge, issued.code)["verified"]


@pytest.mark.parametrize(
    "spoken",
    ["yes", "12345", "1234567", "one two three four five six", "code 123456", "１２３４５６"],
)
def test_invalid_or_ambiguous_codes_never_verify(session_factory, challenge, spoken):
    with session_factory() as session:
        assert not verify(session, challenge, spoken)["verified"]
        session.commit()
        assert resolve_principal(session, "phone", PHONE) is None


def test_three_failures_lock_even_correct_code(session_factory, challenge):
    with session_factory() as session:
        for _ in range(3):
            result = verify(session, challenge, "wrong")
            session.commit()
        assert result["reason"] == "locked"
        assert not verify(session, challenge, challenge[2].code)["verified"]
        assert session.get(PhoneChallenge, challenge[2].challenge_id).attempts == 3


def test_expired_or_other_principal_challenge_is_unusable(session_factory, challenge):
    org, principal, issued = challenge
    with session_factory() as session:
        assert not verify_phone_challenge(
            session,
            org_id=uuid.uuid4(),
            principal_id=principal,
            challenge_id=issued.challenge_id,
            spoken=issued.code,
        )["verified"]
        assert not verify_phone_challenge(
            session,
            org_id=org,
            principal_id=uuid.uuid4(),
            challenge_id=issued.challenge_id,
            spoken=issued.code,
        )["verified"]
        row = session.get(PhoneChallenge, issued.challenge_id)
        assert row.attempts == 0
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
        assert verify(session, challenge, issued.code)["reason"] == "expired"
        session.commit()
        assert (
            pending_phone(
                session, org_id=org, principal_id=principal, challenge_id=issued.challenge_id
            )
            is None
        )


def test_cooldown_and_supersession(session_factory, challenge):
    org, principal, issued = challenge
    with session_factory() as session:
        with pytest.raises(IdentityError):
            issue_phone_challenge(session, org_id=org, principal_id=principal, phone=PHONE)
        session.rollback()
        session.get(PhoneChallenge, issued.challenge_id).created_at = datetime.now(UTC) - timedelta(
            minutes=2
        )
        session.commit()
        second = issue_phone_challenge(session, org_id=org, principal_id=principal, phone=PHONE)
        session.commit()
        assert session.get(PhoneChallenge, issued.challenge_id).state == "canceled"
        assert not verify(session, challenge, issued.code)["verified"]
        assert verify_phone_challenge(
            session,
            org_id=org,
            principal_id=principal,
            challenge_id=second.challenge_id,
            spoken=second.code,
        )["verified"]


def test_unenrolled_or_already_owned_number_cannot_be_issued(session_factory, challenge):
    org, principal, issued = challenge
    with session_factory() as session:
        person = make_principal(session, make_org(session))
        with pytest.raises(IdentityError):
            issue_phone_challenge(
                session, org_id=person.org_id, principal_id=person.id, phone=PHONE
            )
        session.rollback()
        assert verify(session, challenge, issued.code)["verified"]
        session.commit()
        with pytest.raises(IdentityError):
            issue_phone_challenge(session, org_id=org, principal_id=principal, phone=PHONE)


def test_pending_number_not_reserved_and_cannot_steal_verified_owner(session_factory, challenge):
    with session_factory() as session:
        other = make_principal(session, make_org(session), bindings=(("phone", PHONE),))
        session.commit()
        assert not verify(session, challenge, challenge[2].code)["verified"]
        assert resolve_principal(session, "phone", PHONE).id == other.id


def test_concurrent_code_verification_creates_one_binding(session_factory, challenge):
    barrier = threading.Barrier(2)

    def attempt():
        with session_factory() as session:
            barrier.wait()
            result = verify(session, challenge, challenge[2].code)
            session.commit()
            return result["verified"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: attempt(), range(2))) == [False, True]
    with session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ChannelBinding)
                .where(ChannelBinding.channel == "phone")
            )
            == 1
        )


def test_only_verification_mission_can_place_pending_number(session_factory, challenge):
    identifier = make_call(session_factory, challenge)
    provider = Provider()
    assert CallService(session_factory, provider).place(challenge[0], identifier) == "queued"
    assert provider.placements[0][0] == PHONE
    with session_factory() as session:
        assert resolve_principal(session, "phone", PHONE) is None


def test_expired_verification_intent_never_dials(session_factory, challenge):
    identifier = make_call(session_factory, challenge)
    with session_factory() as session:
        session.get(PhoneChallenge, challenge[2].challenge_id).expires_at = datetime.now(
            UTC
        ) - timedelta(seconds=1)
        session.commit()
    provider = Provider()
    assert (
        CallService(session_factory, provider).place(challenge[0], identifier) == "not_authorized"
    )
    assert not provider.placements


def test_real_loop_ignores_invented_code_and_limits_tools(session_factory, challenge):
    identifier = make_call(session_factory, challenge, active=True)
    model = FakeModel(
        proposal("verify_phone_code", {"code": challenge[2].code}), ModelReply("Please retry.")
    )
    runtime, loop = build(session_factory, model, FakeEngine(intent="confirm_action"))
    try:
        assert runtime.run_turn(str(identifier), "wrong code", turn_index=0) == "Please retry."
        offered = model.requests[0]["tools"]
        assert [spec["function"]["name"] for spec in offered] == ["verify_phone_code"]
        with session_factory() as session:
            assert resolve_principal(session, "phone", PHONE) is None
            assert session.get(PhoneChallenge, challenge[2].challenge_id).attempts == 1
            assert session.scalar(select(VoiceTurn.user_text)) == "[confirmation input]"
    finally:
        loop.close()


def test_correct_voice_code_is_idempotent_and_call_finishes(session_factory, challenge):
    identifier = make_call(session_factory, challenge, active=True)
    model = FakeModel(
        proposal("verify_phone_code", {"code": "invented"}), ModelReply("Your phone is verified.")
    )
    runtime, loop = build(session_factory, model, FakeEngine(intent="confirm_action"))
    try:
        assert (
            runtime.run_turn(str(identifier), challenge[2].code, turn_index=0)
            == "Your phone is verified."
        )
        assert (
            runtime.run_turn(str(identifier), challenge[2].code, turn_index=0)
            == "Your phone is verified."
        )
        assert runtime.run_turn(str(identifier), "new", turn_index=1) == REFUSAL
        assert len(model.requests) == 2
        with session_factory() as session:
            assert session.get(VoiceCall, identifier).state == "closed"
            assert resolve_principal(session, "phone", PHONE).id == challenge[1]
            assert session.scalar(select(func.count()).select_from(ToolExecution)) == 1
            assert challenge[2].code not in json.dumps(model.requests[0]["tools"])
    finally:
        loop.close()


def test_unusable_verification_transcript_never_consumes_attempt(session_factory, challenge):
    identifier = make_call(session_factory, challenge, active=True)
    model = FakeModel()
    runtime, loop = build(session_factory, model, FakeEngine(usable="unusable"))
    try:
        assert runtime.run_turn(str(identifier), challenge[2].code, turn_index=0) == CLARIFY
        with session_factory() as session:
            assert session.get(PhoneChallenge, challenge[2].challenge_id).attempts == 0
        assert not model.requests
    finally:
        loop.close()


@pytest.mark.parametrize(
    "channel, mission",
    [
        (Channel.CHAT, None),
        (Channel.VOICE, Mission.ESCALATION),
        (Channel.VOICE, Mission.CLAIM_CHECK),
    ],
)
def test_verification_tool_denied_outside_narrow_call(session_factory, challenge, channel, mission):
    org, principal, issued = challenge
    dispatcher = Dispatcher(build_registry(), ApprovalPolicy(timedelta(minutes=10), 3, False))
    with session_factory() as session:
        context = ToolContext(
            org, principal, channel, mission, "probe", phone_challenge_id=issued.challenge_id
        )
        result = dispatcher.dispatch(session, context, "verify_phone_code", {"code": issued.code})
        session.commit()
        assert result.status == "denied"
        assert session.get(PhoneChallenge, issued.challenge_id).attempts == 0


def test_leading_zero_code_and_verification_history_are_preserved_safely(
    session_factory,
    monkeypatch,
):
    monkeypatch.setattr("svaar.identity.phones.secrets.randbelow", lambda _: 42)
    with session_factory() as session:
        org = make_org(session)
        person = make_principal(session, org, bindings=(("caspian:telegram", "demo-zero"),))
        issued = issue_phone_challenge(session, org_id=org.id, principal_id=person.id, phone=PHONE)
        assert issued.code == "000042"
        session.commit()
        data = org.id, person.id, issued
    identifier = make_call(session_factory, data, active=True)
    model = FakeModel(
        proposal("verify_phone_code"),
        ModelReply("Please repeat."),
        proposal("verify_phone_code"),
        ModelReply("Verified."),
    )
    runtime, loop = build(session_factory, model, FakeEngine(intent="confirm_action"))
    try:
        runtime.run_turn(str(identifier), "wrong code", turn_index=0)
        runtime.run_turn(str(identifier), "000042", turn_index=1)
        # New verification turns contain only system policy plus current text.
        assert len(model.requests[2]["messages"]) == 2
        with session_factory() as session:
            assert resolve_principal(session, "phone", PHONE).id == data[1]
    finally:
        loop.close()


def test_unclear_short_speech_never_consumes_phone_attempt(session_factory, challenge):
    from svaar.agent.loop import CLARIFY

    identifier = make_call(session_factory, challenge, active=True)
    model = FakeModel()
    runtime, loop = build(session_factory, model, FakeEngine(intent="confirm_action"))
    try:
        assert runtime.run_turn(str(identifier), "wrong", turn_index=0) == CLARIFY
        assert not model.requests
        with session_factory() as session:
            assert session.get(PhoneChallenge, challenge[2].challenge_id).attempts == 0
            assert resolve_principal(session, "phone", PHONE) is None
    finally:
        loop.close()
