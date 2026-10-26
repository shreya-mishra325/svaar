"""Voice failures queue durable private follow-ups; no provider request is made."""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from factories import make_org, make_principal
from sqlalchemy import func, select
from test_chat_runtime import Transport

from svaar.agent.models import Conversation, InboundRecord, OutboxMessage
from svaar.agent.notifications import FOLLOW_UP, enqueue_voice_fallback
from svaar.agent.outbox import OutboxSender
from svaar.identity.models import ChannelBinding
from svaar.voice.models import VoiceCall, VoiceTurn
from svaar.voice.runtime import FALLBACK, QUEUED_FALLBACK, VoiceRuntime


def setup_call(sessions, routes=1):
    with sessions() as session:
        org = make_org(session)
        person = make_principal(
            session, org, bindings=(("phone", "+15555550123"), ("fake", "user"))
        )
        phone = session.scalar(select(ChannelBinding).where(ChannelBinding.channel == "phone"))
        call = VoiceCall(
            org_id=org.id,
            principal_id=person.id,
            phone_binding_id=phone.id,
            mission="escalation",
            state="active",
        )
        session.add(call)
        for index in range(routes):
            conversation = Conversation(
                org_id=org.id,
                principal_id=person.id,
                channel="fake",
                connection_id="connection-1",
                thread_id=f"thread-{index}",
            )
            session.add(conversation)
            session.flush()
            session.add(
                InboundRecord(
                    conversation_id=conversation.id,
                    channel="fake",
                    connection_id="connection-1",
                    external_message_id=f"anchor-{index}",
                    sender_address="user",
                    payload_hash="0" * 64,
                    state="processed",
                )
            )
        session.commit()
        return org.id, person.id, call.id


@pytest.mark.parametrize("mode", ["unavailable", "tool_limit", "exception"])
def test_failure_followup_is_private_durable_and_deduplicated(session_factory, mode):
    org, principal, identifier = setup_call(session_factory)
    executions = []

    def execute(*args):
        executions.append(True)
        if mode == "exception":
            raise RuntimeError("private-transcript")
        return "I will message you.", mode

    runner = VoiceRuntime(session_factory, execute, notify_failure=enqueue_voice_fallback)
    assert runner.run_turn(str(identifier), "private-transcript", turn_index=0) == QUEUED_FALLBACK
    assert runner.run_turn(str(identifier), "private-transcript", turn_index=0) == QUEUED_FALLBACK
    assert executions == [True]
    with session_factory() as session:
        rows = list(session.scalars(select(OutboxMessage)))
        assert len(rows) == 1 and rows[0].body == FOLLOW_UP
        assert "private-transcript" not in rows[0].body
    transport = Transport()
    sender = OutboxSender(session_factory, transport, channel="fake", connection_id="connection-1")
    assert sender.send_one() is not None and sender.send_one() is None
    assert transport.sent[0][0].sender_address == "user"


@pytest.mark.parametrize("routes", [0, 2])
def test_missing_or_ambiguous_chat_never_promises_delivery(session_factory, routes):
    _, _, identifier = setup_call(session_factory, routes)
    runner = VoiceRuntime(
        session_factory,
        lambda *args: ("late", "unavailable"),
        notify_failure=enqueue_voice_fallback,
    )
    assert runner.run_turn(str(identifier), "hello", turn_index=0) == FALLBACK
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(OutboxMessage)) == 0


def test_notification_failure_preserves_unknown_execution(session_factory):
    _, _, identifier = setup_call(session_factory)

    def fail(*args):
        raise RuntimeError("private")

    runner = VoiceRuntime(session_factory, fail, notify_failure=fail)
    assert runner.run_turn(str(identifier), "hello", turn_index=0) == FALLBACK
    with session_factory() as session:
        assert session.scalar(select(VoiceTurn.state)) == "unknown"
        assert session.scalar(select(func.count()).select_from(OutboxMessage)) == 0


def test_interrupted_turn_retry_queues_without_reexecuting(session_factory):
    _, _, identifier = setup_call(session_factory)

    def interrupt(*args):
        raise KeyboardInterrupt()

    runner = VoiceRuntime(session_factory, interrupt, notify_failure=enqueue_voice_fallback)
    with pytest.raises(KeyboardInterrupt):
        runner.run_turn(str(identifier), "hello", turn_index=0)
    assert runner.run_turn(str(identifier), "hello", turn_index=0) == QUEUED_FALLBACK
    assert runner.run_turn(str(identifier), "hello", turn_index=0) == QUEUED_FALLBACK


def test_concurrent_notification_claims_use_one_key_and_distinct_ordinals(session_factory):
    org, principal, identifier = setup_call(session_factory)
    barrier = threading.Barrier(2)

    def enqueue(index):
        with session_factory.begin() as session:
            barrier.wait()
            return enqueue_voice_fallback(session, org, principal, identifier, index)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(enqueue, [0, 1])) == [True, True]
    with session_factory() as session:
        assert sorted(session.scalars(select(OutboxMessage.ordinal))) == [0, 1]
    with session_factory.begin() as session:
        assert enqueue_voice_fallback(session, org, principal, identifier, 0)
        assert not enqueue_voice_fallback(session, uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), 0)
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(OutboxMessage)) == 2


def test_revocation_blocks_a_queued_followup(session_factory):
    org, principal, identifier = setup_call(session_factory)
    with session_factory.begin() as session:
        assert enqueue_voice_fallback(session, org, principal, identifier, 0)
    with session_factory.begin() as session:
        binding = session.scalar(select(ChannelBinding).where(ChannelBinding.channel == "fake"))
        binding.verified_at = None
    transport = Transport()
    sender = OutboxSender(session_factory, transport, channel="fake", connection_id="connection-1")
    sender.send_one()
    assert not transport.sent


def test_clarification_and_authorization_refusal_do_not_notify(session_factory):
    _, _, identifier = setup_call(session_factory)
    runner = VoiceRuntime(
        session_factory,
        lambda *args: ("Please repeat.", "clarification_required"),
        notify_failure=enqueue_voice_fallback,
    )
    assert runner.run_turn(str(identifier), "hello", turn_index=0) == "Please repeat."
    assert runner.run_turn(str(uuid.uuid4()), "hello", turn_index=0) != QUEUED_FALLBACK
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(OutboxMessage)) == 0


@pytest.mark.parametrize("status", ["no-answer", "busy", "failed", "canceled", "stopped", "error"])
def test_failed_call_receipt_queues_once_atomically(session_factory, status):
    from svaar.agent.notifications import CALL_FAILURE_FOLLOW_UP, enqueue_call_failure
    from svaar.voice.models import VoiceWebhookEvent
    from svaar.voice.status import StatusPayload, ingest_status

    _, _, identifier = setup_call(session_factory)
    execution, agent = uuid.uuid4(), uuid.uuid4()
    with session_factory() as session:
        call = session.get(VoiceCall, identifier)
        call.execution_id, call.provider_agent_id = execution, agent
        session.commit()
    body = StatusPayload(id=execution, agent_id=agent, status=status)
    assert ingest_status(session_factory, body, b"synthetic", enqueue_call_failure) == "recorded"
    assert ingest_status(session_factory, body, b"synthetic", enqueue_call_failure) == "duplicate"
    with session_factory() as session:
        rows = session.scalars(select(OutboxMessage)).all()
        assert len(rows) == 1 and rows[0].body == CALL_FAILURE_FOLLOW_UP
        assert rows[0].notification_key == f"voice-call-failure:{identifier}"
        assert session.scalar(select(func.count()).select_from(VoiceWebhookEvent)) == 1


@pytest.mark.parametrize("routes", [0, 2])
def test_failed_call_never_guesses_chat_recipient(session_factory, routes):
    from svaar.agent.notifications import enqueue_call_failure

    org, principal, identifier = setup_call(session_factory, routes=routes)
    with session_factory.begin() as session:
        assert not enqueue_call_failure(session, org, principal, identifier)
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(OutboxMessage)) == 0


def test_notification_error_rolls_back_status_for_redelivery(session_factory):
    from svaar.agent.notifications import enqueue_call_failure
    from svaar.voice.models import VoiceWebhookEvent
    from svaar.voice.status import StatusPayload, ingest_status

    _, _, identifier = setup_call(session_factory)
    execution, agent = uuid.uuid4(), uuid.uuid4()
    with session_factory() as session:
        call = session.get(VoiceCall, identifier)
        call.execution_id, call.provider_agent_id = execution, agent
        session.commit()
    body = StatusPayload(id=execution, agent_id=agent, status="busy")

    def fail(session, org, principal, call):
        enqueue_call_failure(session, org, principal, call)
        raise RuntimeError("synthetic-enqueue-failure")

    with pytest.raises(RuntimeError, match="synthetic-enqueue-failure"):
        ingest_status(session_factory, body, b"synthetic", fail)
    with session_factory() as session:
        assert session.get(VoiceCall, identifier).state == "active"
        assert session.scalar(select(func.count()).select_from(VoiceWebhookEvent)) == 0
        assert session.scalar(select(func.count()).select_from(OutboxMessage)) == 0
    assert ingest_status(session_factory, body, b"synthetic", enqueue_call_failure) == "recorded"


@pytest.mark.parametrize("status", ["completed", "balance-low", "in-progress", "future-status"])
def test_non_failure_status_never_queues_call_failure(session_factory, status):
    from svaar.voice.status import StatusPayload, ingest_status

    _, _, identifier = setup_call(session_factory)
    execution, agent = uuid.uuid4(), uuid.uuid4()
    with session_factory() as session:
        call = session.get(VoiceCall, identifier)
        call.execution_id, call.provider_agent_id = execution, agent
        session.commit()

    def forbidden(*args):
        pytest.fail("Non-failure status reached failure notifier")

    ingest_status(
        session_factory,
        StatusPayload(id=execution, agent_id=agent, status=status),
        b"synthetic",
        forbidden,
    )


def test_failed_status_route_uses_composed_private_outbox(session_factory, database_url):
    from fastapi.testclient import TestClient

    from svaar.app import create_app
    from svaar.config import Settings
    from svaar.voice.status import HEADER

    _, _, identifier = setup_call(session_factory)
    execution, agent = uuid.uuid4(), uuid.uuid4()
    with session_factory() as session:
        call = session.get(VoiceCall, identifier)
        call.execution_id, call.provider_agent_id = execution, agent
        session.commit()
    secret = "s" * 32
    settings = Settings(_env_file=None, database_url=database_url, voice_status_secret=secret)
    with TestClient(create_app(settings), client=("13.203.39.153", 50000)) as client:
        body = {"id": str(execution), "agent_id": str(agent), "status": "no-answer"}
        for expected in ["recorded", "duplicate"]:
            response = client.post("/api/v1/voice/status", headers={HEADER: secret}, json=body)
            assert response.status_code == 200 and response.json()["status"] == expected
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(OutboxMessage)) == 1
