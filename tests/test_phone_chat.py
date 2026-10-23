"""Private chat issuance to fake voice verification through real persistence and gates."""

import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from test_agent_loop import FakeEngine, FakeModel, proposal
from test_chat_runtime import Model, Transport, enroll, incoming
from test_voice_calls import Provider
from test_voice_runtime import build

from svaar.actions.catalog import build_registry
from svaar.actions.dispatcher import ApprovalPolicy, Dispatcher
from svaar.agent.llm import ModelReply
from svaar.agent.loop import AgentLoop
from svaar.agent.models import InboundRecord, Message, OutboxMessage
from svaar.agent.outbox import OutboxSender
from svaar.agent.runtime import ChatRuntime
from svaar.decisions.service import DecisionService
from svaar.identity.models import PhoneChallenge
from svaar.identity.service import resolve_principal
from svaar.voice.calls import CallService, prepare_phone_verification_call
from svaar.voice.models import VoiceCall

PHONE = "+15555550123"


@pytest.fixture
def chat(session_factory):
    model = Model()
    agent = AgentLoop(
        model,
        Dispatcher(build_registry(), ApprovalPolicy(timedelta(minutes=10), 3, False)),
        DecisionService(None, high=0.85, low=0.55),
    )
    runtime = ChatRuntime(
        session_factory, agent, prepare_phone_call=prepare_phone_verification_call
    )
    yield runtime, model
    agent.close()


def request(runtime, sessions):
    enroll(runtime, sessions)
    message = incoming("/verify_phone " + PHONE, external_message_id="phone-request")
    assert runtime.process(message).status == "phone_verification_pending"
    return message


def deliverer(sessions, transport):
    return OutboxSender(sessions, transport, channel="fake", connection_id="connection-1")


def test_enroll_private_code_fake_call_and_exact_voice_verification(session_factory, chat):
    runtime, model = chat
    message = request(runtime, session_factory)
    assert runtime.process(message).status == "duplicate"
    assert not model.requests
    with session_factory() as session:
        call = session.scalar(select(VoiceCall))
        org_id, call_id = call.org_id, call.id
        assert call.state == "pending" and call.mission == "phone_verify"
        assert resolve_principal(session, "phone", PHONE) is None
        assert session.scalar(select(func.count()).select_from(PhoneChallenge)) == 1
        assert session.scalar(select(func.count()).select_from(OutboxMessage)) == 2
        assert session.scalar(select(func.count()).select_from(Message)) == 0
    transport = Transport()
    sender = deliverer(session_factory, transport)
    assert sender.send_one() and sender.send_one()
    assert sender.send_one() is None
    code_message = transport.sent[1][1]
    code = re.search(r"code: ([0-9]{6})", code_message).group(1)
    assert transport.sent[1][0].sender_address == "user-1"
    assert "started separately" in code_message
    provider = Provider()
    calls = CallService(session_factory, provider)
    assert calls.place(org_id, call_id) == "queued"
    assert calls.refresh(org_id, call_id) == "active"
    voice_model = FakeModel(proposal("verify_phone_code"), ModelReply("Your phone is verified."))
    runner, loop = build(session_factory, voice_model, FakeEngine(intent="confirm_action"))
    try:
        assert runner.run_turn(str(call_id), code, turn_index=0) == "Your phone is verified."
        assert runner.run_turn(str(call_id), code, turn_index=0) == "Your phone is verified."
        with session_factory() as session:
            assert resolve_principal(session, "phone", PHONE).org_id == org_id
    finally:
        loop.close()
    assert (
        runtime.process(incoming("whoami", external_message_id="after-phone")).status == "processed"
    )
    assert code not in str(model.requests) and PHONE not in str(model.requests)


@pytest.mark.parametrize(
    "text",
    [
        "/verify_phone",
        "/verify_phone invalid",
        "/verify_phone +15555550123 extra",
        "/VERIFY_PHONE invalid",
    ],
)
def test_invalid_phone_command_is_handled_without_model_or_history(session_factory, chat, text):
    runtime, model = chat
    enroll(runtime, session_factory)
    message = incoming(text, external_message_id="invalid-phone")
    assert runtime.process(message).status == "phone_verification_rejected"
    assert runtime.process(message).status == "duplicate"
    assert not model.requests
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PhoneChallenge)) == 0
        assert session.scalar(select(func.count()).select_from(VoiceCall)) == 0
        assert session.scalar(select(func.count()).select_from(Message)) == 0


def test_phone_command_requires_enrollment_and_authenticated_sender(session_factory, chat):
    runtime, model = chat
    command = "/verify_phone " + PHONE
    assert runtime.process(incoming(command)).status == "enrollment_required"
    assert (
        runtime.process(incoming(command, sender_authenticated=False)).status == "untrusted_sender"
    )
    assert not model.requests
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PhoneChallenge)) == 0


def test_cooldown_rejection_preserves_original_challenge_and_intent(session_factory, chat):
    runtime, model = chat
    request(runtime, session_factory)
    assert (
        runtime.process(incoming("/verify_phone " + PHONE, external_message_id="too-soon")).status
        == "phone_verification_rejected"
    )
    assert not model.requests
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PhoneChallenge)) == 1
        assert session.scalar(select(PhoneChallenge.state)) == "pending"
        assert session.scalar(select(func.count()).select_from(VoiceCall)) == 1


def test_database_failure_rolls_back_challenge_intent_code_and_dedupe(
    session_factory, chat, monkeypatch
):
    runtime, model = chat
    enroll(runtime, session_factory)
    message = incoming("/verify_phone " + PHONE, external_message_id="retry-phone")
    original = runtime._enqueue

    def fail(*args, **kwargs):
        raise RuntimeError("simulated durable outbox failure")

    monkeypatch.setattr(runtime, "_enqueue", fail)
    with pytest.raises(RuntimeError):
        runtime.process(message)
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PhoneChallenge)) == 0
        assert session.scalar(select(func.count()).select_from(VoiceCall)) == 0
        assert session.scalar(select(func.count()).select_from(OutboxMessage)) == 1
        assert session.scalar(select(func.count()).select_from(InboundRecord)) == 1
    monkeypatch.setattr(runtime, "_enqueue", original)
    assert runtime.process(message).status == "phone_verification_pending"
    assert not model.requests


@pytest.mark.parametrize("state", ["expired", "canceled", "locked", "verified"])
def test_stale_secret_code_is_never_sent(session_factory, chat, state):
    runtime, _ = chat
    request(runtime, session_factory)
    transport = Transport()
    sender = deliverer(session_factory, transport)
    sender.send_one()  # Enrollment reply only.
    with session_factory() as session:
        challenge = session.scalar(select(PhoneChallenge))
        if state == "expired":
            challenge.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        else:
            challenge.state = state
        session.commit()
    sender.send_one()
    assert len(transport.sent) == 1
    with session_factory() as session:
        secret = session.scalar(
            select(OutboxMessage).where(OutboxMessage.phone_challenge_id.is_not(None))
        )
        assert secret.state == "failed" and secret.error_code == "phone_challenge_unavailable"


def test_missing_composition_callback_does_not_issue_challenge(session_factory, chat):
    runtime, _ = chat
    runtime.prepare_phone_call = None
    enroll(runtime, session_factory)
    assert (
        runtime.process(incoming("/verify_phone " + PHONE)).status == "phone_verification_rejected"
    )
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PhoneChallenge)) == 0


def test_superseded_pending_code_is_withheld_and_only_new_code_sent(session_factory, chat):
    runtime, _ = chat
    request(runtime, session_factory)
    with session_factory() as session:
        old = session.scalar(select(PhoneChallenge))
        old.created_at = datetime.now(UTC) - timedelta(minutes=2)
        session.commit()
    assert (
        runtime.process(incoming("/verify_phone " + PHONE, external_message_id="new-code")).status
        == "phone_verification_pending"
    )
    transport = Transport()
    sender = deliverer(session_factory, transport)
    while sender.send_one() is not None:
        pass
    assert len(transport.sent) == 2  # Enrollment plus the new code.
    with session_factory() as session:
        assert list(
            session.scalars(
                select(OutboxMessage.state)
                .where(OutboxMessage.phone_challenge_id.is_not(None))
                .order_by(OutboxMessage.created_at)
            )
        ) == ["failed", "sent"]


def test_downgrade_refuses_unresolved_code_deliveries(
    session_factory,
    chat,
    database_url,
    monkeypatch,
):
    from alembic import command
    from alembic.config import Config

    runtime, _ = chat
    request(runtime, session_factory)
    monkeypatch.setenv("SVAAR_DATABASE_URL", database_url)
    with pytest.raises(RuntimeError, match="Reconcile phone challenge deliveries"):
        command.downgrade(Config("alembic.ini"), "0007")
    with session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxMessage)
                .where(
                    OutboxMessage.phone_challenge_id.is_not(None),
                )
            )
            == 1
        )
