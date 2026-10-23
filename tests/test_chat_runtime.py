"""Real PostgreSQL recovery/concurrency checks with fake model and transport only."""

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from svaar.actions.catalog import build_registry
from svaar.actions.dispatcher import ApprovalPolicy, ConfirmationTicket, Dispatcher
from svaar.actions.models import ToolExecution
from svaar.agent.llm import ModelReply, ToolRequest
from svaar.agent.loop import AgentLoop, TurnResult
from svaar.agent.models import Conversation, InboundRecord, Message, OutboxMessage
from svaar.agent.outbox import OutboxSender
from svaar.agent.runtime import ChatRuntime
from svaar.agent.transport import (
    DeliveryReceipt,
    DeliveryRejectedError,
    DeliveryUncertainError,
    InboundMessage,
)
from svaar.decisions.service import DecisionService
from svaar.identity.models import ChannelBinding, Principal, Role
from svaar.identity.service import create_invite, create_org

pytestmark = pytest.mark.postgres


class Model:
    def __init__(self):
        self.requests = []

    def complete(self, messages, tools, *, timeout):
        self.requests.append(messages.copy())
        if messages[-1]["role"] == "tool":
            return ModelReply("You are enrolled.")
        return ModelReply("", (ToolRequest("call", "whoami", {}),))


@pytest.fixture
def model():
    return Model()


@pytest.fixture
def runtime(session_factory, model):
    dispatcher = Dispatcher(build_registry(), ApprovalPolicy(timedelta(minutes=10), 3, False))
    agent = AgentLoop(model, dispatcher, DecisionService(None, high=0.85, low=0.55))
    yield ChatRuntime(session_factory, agent)
    agent.close()


def incoming(text="whoami", **kwargs):
    return InboundMessage(
        "fake",
        "connection-1",
        kwargs.pop("external_message_id", "message-1"),
        kwargs.pop("thread_id", "thread-1"),
        kwargs.pop("sender_address", "user-1"),
        text,
        kwargs.pop("sender_authenticated", True),
    )


def enroll(runtime, sessions, *, user="user-1", thread="thread-1"):
    with sessions() as session:
        org = create_org(session, "Test team")
        issued = create_invite(session, org.id, Role.DEV, timedelta(hours=1))
        code = issued.code
        session.commit()
    message = incoming(
        "/join " + code, external_message_id="join-" + user, sender_address=user, thread_id=thread
    )
    result = runtime.process(message)
    assert result.status == "enrolled"
    return message


def count(sessions, model):
    with sessions() as session:
        return session.scalar(select(func.count()).select_from(model))


class Transport:
    def __init__(self, status="sent", failure=None):
        self.status, self.failure = status, failure
        self.sent = []

    def send(self, target, body):
        self.sent.append((target, body))
        if self.failure:
            raise self.failure
        return DeliveryReceipt("delivery-" + str(len(self.sent)), self.status)

    def receipt(self, delivery_id, *, thread_id):
        return DeliveryReceipt(delivery_id, self.status)


def sender(sessions, transport, **kwargs):
    return OutboxSender(sessions, transport, channel="fake", connection_id="connection-1", **kwargs)


def test_vertical_slice_enroll_whoami_delivery_and_duplicate(runtime, session_factory, model):
    join = enroll(runtime, session_factory)
    assert runtime.process(join).status == "duplicate"
    assert len(model.requests) == 0
    assert runtime.process(incoming()).status == "processed"
    assert runtime.process(incoming()).status == "duplicate"
    assert count(session_factory, ToolExecution) == 1
    assert count(session_factory, Message) == 2
    assert count(session_factory, Principal) == 1
    transport = Transport()
    outbox = sender(session_factory, transport)
    assert outbox.send_one() and outbox.send_one()
    assert outbox.send_one() is None
    assert len(transport.sent) == 2
    with session_factory() as session:
        assert set(session.scalars(select(OutboxMessage.state))) == {"sent"}
        history = list(session.scalars(select(Message).order_by(Message.position)))
        assert [row.role for row in history] == ["user", "assistant"]
        assert all(join.text.split()[1] not in row.content for row in history)


def test_untrusted_sender_cannot_consume_invite_or_use_existing_binding(runtime, session_factory):
    join = enroll(runtime, session_factory)
    result = runtime.process(replace(join, sender_authenticated=False))
    assert result.status == "untrusted_sender"
    assert runtime.process(incoming(sender_authenticated=False)).status == "untrusted_sender"
    assert count(session_factory, Principal) == 1
    assert count(session_factory, ToolExecution) == 0


def test_unknown_sender_and_invalid_invite_have_no_persisted_payload(runtime, session_factory):
    assert runtime.process(incoming()).status == "enrollment_required"
    assert runtime.process(incoming("/join invalid")).status == "invite_rejected"
    assert count(session_factory, Conversation) == 0
    assert count(session_factory, InboundRecord) == 0


def test_changed_payload_under_same_message_id_is_refused(runtime, session_factory):
    enroll(runtime, session_factory)
    runtime.process(incoming())
    assert runtime.process(incoming("different text")).status == "message_id_conflict"
    assert count(session_factory, ToolExecution) == 1


def test_conversation_cannot_cross_principal_or_organization(runtime, session_factory):
    enroll(runtime, session_factory)
    enroll(runtime, session_factory, user="user-2", thread="thread-2")
    result = runtime.process(incoming(sender_address="user-2", external_message_id="other"))
    assert result.status == "thread_not_authorized"
    assert count(session_factory, ToolExecution) == 0


def test_memory_is_persisted_in_order_and_scoped(runtime, session_factory, model):
    enroll(runtime, session_factory)
    runtime.process(incoming("first private question"))
    runtime.process(incoming("second question", external_message_id="message-2"))
    history = model.requests[2]
    assert history[1:3] == [
        {"role": "user", "content": "first private question"},
        {"role": "assistant", "content": "You are enrolled."},
    ]
    enroll(runtime, session_factory, user="user-2", thread="thread-2")
    runtime.process(
        incoming(
            "other user",
            sender_address="user-2",
            thread_id="thread-2",
            external_message_id="message-3",
        )
    )
    assert all("first private" not in item["content"] for item in model.requests[4])


def test_concurrent_duplicate_does_not_start_a_second_turn(runtime, session_factory):
    enroll(runtime, session_factory)
    entered, release = threading.Event(), threading.Event()
    original = runtime.agent.run

    def block(*args, **kwargs):
        args[0].commit()  # Advisory ownership must survive dispatcher commits.
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    runtime.agent.run = block
    with ThreadPoolExecutor(max_workers=1) as executor:
        running = executor.submit(runtime.process, incoming())
        try:
            assert entered.wait(5)
            assert runtime.process(incoming()).status == "busy"
        finally:
            release.set()
        assert running.result(timeout=5).status == "processed"
    assert count(session_factory, ToolExecution) == 1


def test_commit_then_crash_requires_reconciliation_without_replaying(runtime, session_factory):
    enroll(runtime, session_factory)
    calls = []

    def crash(session, context, text, **kwargs):
        calls.append(text)
        runtime.agent.dispatcher.dispatch(session, context, "whoami", {})
        session.commit()
        raise RuntimeError("private failure")

    runtime.agent.run = crash
    assert runtime.process(incoming()).status == "reconciliation_required"
    assert runtime.process(incoming()).status == "reconciliation_required"
    assert len(calls) == 1 and count(session_factory, ToolExecution) == 1
    with session_factory() as session:
        assert "unknown" in set(session.scalars(select(InboundRecord.state)))


def test_abandoned_processing_marker_never_replays(runtime, session_factory):
    enroll(runtime, session_factory)

    def crash(*args, **kwargs):
        raise KeyboardInterrupt()

    runtime.agent.run = crash
    with pytest.raises(KeyboardInterrupt):
        runtime.process(incoming())
    assert runtime.process(incoming()).status == "reconciliation_required"


def test_nonce_ticket_never_enters_history(runtime, session_factory, model):
    enroll(runtime, session_factory)
    import uuid

    def ticket(session, context, text, **kwargs):
        return TurnResult(
            "Waiting for confirmation.",
            "confirmation_required",
            (ConfirmationTicket(uuid.uuid4(), context.principal_id, "test", "987654"),),
        )

    original = runtime.agent.run
    runtime.agent.run = ticket
    runtime.process(incoming())
    runtime.agent.run = original
    runtime.process(incoming("987654", external_message_id="confirmation"))
    runtime.process(incoming("next question", external_message_id="next"))
    with session_factory() as session:
        texts = list(session.scalars(select(Message.content)))
        assert all("987654" not in value for value in texts)
        assert any("987654" in value for value in session.scalars(select(OutboxMessage.body)))
    assert all("987654" not in str(request) for request in model.requests[2:])


def test_outbox_queued_is_not_resent_and_receipt_can_be_reconciled(runtime, session_factory):
    enroll(runtime, session_factory)
    transport = Transport(status="queued")
    worker = sender(session_factory, transport)
    row_id = worker.send_one()
    assert worker.send_one() is None
    assert len(transport.sent) == 1
    transport.status = "sent"
    assert worker.refresh(row_id)
    with session_factory() as session:
        assert session.get(OutboxMessage, row_id).state == "sent"


@pytest.mark.parametrize(
    "failure,state",
    [
        (DeliveryUncertainError("private"), "unknown"),
        (RuntimeError("private"), "unknown"),
        (DeliveryRejectedError("private"), "failed"),
    ],
)
def test_uncertain_or_permanent_delivery_is_not_retried(runtime, session_factory, failure, state):
    enroll(runtime, session_factory)
    transport = Transport(failure=failure)
    worker = sender(session_factory, transport)
    row_id = worker.send_one()
    assert worker.send_one() is None
    assert len(transport.sent) == 1
    with session_factory() as session:
        row = session.get(OutboxMessage, row_id)
        assert row.state == state and "private" not in (row.error_code or "")


def test_explicit_safe_rejection_has_bounded_retries(runtime, session_factory):
    enroll(runtime, session_factory)
    transport = Transport(failure=DeliveryRejectedError("busy", retryable=True))
    worker = sender(session_factory, transport, max_attempts=2)
    row_id = worker.send_one()
    assert worker.send_one() is None  # backoff has not elapsed
    with session_factory() as session:
        session.get(OutboxMessage, row_id).next_attempt_at = datetime.now(UTC) - timedelta(
            seconds=1
        )
        session.commit()
    worker.send_one()
    assert worker.send_one() is None
    with session_factory() as session:
        row = session.get(OutboxMessage, row_id)
        assert row.state == "failed" and row.attempts == 2


def test_outbox_rechecks_verified_recipient_before_send(runtime, session_factory):
    enroll(runtime, session_factory)
    with session_factory() as session:
        session.scalar(select(ChannelBinding)).verified_at = None
        session.commit()
    transport = Transport()
    worker = sender(session_factory, transport)
    row_id = worker.send_one()
    assert not transport.sent
    with session_factory() as session:
        assert session.get(OutboxMessage, row_id).error_code == "recipient_not_authorized"


def test_crash_during_send_leaves_nonretryable_sending_state(runtime, session_factory):
    enroll(runtime, session_factory)
    transport = Transport(failure=KeyboardInterrupt())
    worker = sender(session_factory, transport)
    with pytest.raises(KeyboardInterrupt):
        worker.send_one()
    assert worker.send_one() is None
    assert len(transport.sent) == 1
    with session_factory() as session:
        assert session.scalar(select(OutboxMessage.state)) == "sending"


def test_worker_never_claims_another_connection(runtime, session_factory):
    enroll(runtime, session_factory)
    worker = OutboxSender(session_factory, Transport(), channel="fake", connection_id="other")
    assert worker.send_one() is None


def test_repeated_join_command_never_leaks_into_model_or_history(runtime, session_factory, model):
    join = enroll(runtime, session_factory)
    runtime.process(replace(join, external_message_id="second-join"))
    assert not model.requests
    assert count(session_factory, Message) == 0
    assert count(session_factory, Principal) == 1


def test_concurrent_outbox_workers_do_not_duplicate_delivery(runtime, session_factory):
    enroll(runtime, session_factory)
    entered, release = threading.Event(), threading.Event()
    transport = Transport()
    original = transport.send

    def block(target, body):
        entered.set()
        assert release.wait(5)
        return original(target, body)

    transport.send = block
    worker = sender(session_factory, transport)
    with ThreadPoolExecutor(max_workers=1) as executor:
        running = executor.submit(worker.send_one)
        try:
            assert entered.wait(5)
            assert worker.send_one() is None
        finally:
            release.set()
        assert running.result(timeout=5)
    assert len(transport.sent) == 1
