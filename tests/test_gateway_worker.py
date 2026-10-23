"""Durable gateway restart/replay tests with fake transports and PostgreSQL."""

import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import func, select, text
from test_chat_runtime import Model, Transport, enroll, incoming

from svaar.actions.catalog import build_registry
from svaar.actions.dispatcher import ApprovalPolicy, Dispatcher
from svaar.actions.models import ToolExecution
from svaar.agent.loop import AgentLoop
from svaar.agent.models import GatewayCursor, InboundRecord
from svaar.agent.runtime import ChatRuntime
from svaar.agent.transport import PollBatch
from svaar.agent.worker import GatewayWorker
from svaar.decisions.service import DecisionService
from svaar.gateway import main

pytestmark = pytest.mark.postgres


class PollTransport(Transport):
    def __init__(self):
        super().__init__()
        self.events, self.cursors = [], []
        self.failure = None

    def poll(self, *, after_seq, limit):
        self.cursors.append(after_seq)
        if self.failure:
            raise self.failure
        page = [(seq, message) for seq, message in self.events if seq > after_seq][:limit]
        return PollBatch(tuple(message for _, message in page), page[-1][0] if page else after_seq)


@pytest.fixture
def components(session_factory):
    agent = AgentLoop(
        Model(),
        Dispatcher(build_registry(), ApprovalPolicy(timedelta(minutes=10), 3, False)),
        DecisionService(None, high=0.85, low=0.55),
    )
    runtime = ChatRuntime(session_factory, agent)
    transport = PollTransport()
    worker = GatewayWorker(
        session_factory, runtime, transport, channel="fake", connection_id="connection-1"
    )
    yield runtime, transport, worker
    agent.close()


def test_poll_process_deliver_and_restart_uses_persisted_cursor(components, session_factory):
    runtime, transport, worker = components
    join = enroll(runtime, session_factory)
    transport.events = [(1, join), (2, incoming())]
    assert worker.tick() == "ready"
    assert len(transport.sent) == 2
    restarted = GatewayWorker(
        session_factory, runtime, transport, channel="fake", connection_id="connection-1"
    )
    assert restarted.tick() == "ready"
    assert transport.cursors == [0, 2]
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ToolExecution)) == 1
        assert session.get(GatewayCursor, worker.stream_key).last_seq == 2


def test_crash_before_cursor_commit_replays_only_through_dedupe(components, session_factory):
    runtime, transport, worker = components
    enroll(runtime, session_factory)
    transport.events = [(1, incoming())]
    original = worker._state

    def fail_cursor(state, *, cursor=None, error=None):
        if cursor is not None:
            raise RuntimeError("simulated crash")
        original(state, error=error)

    worker._state = fail_cursor
    assert worker.tick() == "error"
    worker._state = original
    assert worker.tick() == "ready"
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ToolExecution)) == 1
        assert session.get(GatewayCursor, worker.stream_key).last_seq == 1


def test_untrusted_page_never_calls_agent_or_outbox_or_advances(components, session_factory):
    _, transport, worker = components
    transport.events = [(1, incoming(sender_authenticated=False))]
    assert worker.tick() == "blocked_identity"
    assert not transport.sent
    with session_factory() as session:
        row = session.get(GatewayCursor, worker.stream_key)
        assert row.last_seq == 0
        assert row.error_code == "sender_identity_unverified"
        assert session.scalar(select(func.count()).select_from(InboundRecord)) == 0


def test_failed_poll_keeps_cursor_and_sanitizes_error(components, session_factory):
    _, transport, worker = components
    transport.failure = RuntimeError("private-provider-payload")
    assert worker.tick() == "error"
    with session_factory() as session:
        row = session.get(GatewayCursor, worker.stream_key)
        assert row.last_seq == 0 and row.error_code == "runtime_unavailable"


def test_second_worker_cannot_own_stream(components, db_engine):
    _, transport, worker = components
    with db_engine.connect() as owner:
        owner.execute(text("SELECT pg_advisory_lock(:key)"), {"key": worker.lock_key})
        try:
            assert worker.tick() == "busy"
            assert transport.cursors == []
        finally:
            owner.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": worker.lock_key})


def test_wrong_connection_does_not_advance(components, session_factory):
    _, transport, worker = components
    transport.events = [(1, replace(incoming(), connection_id="another"))]
    assert worker.tick() == "error"
    with session_factory() as session:
        assert session.get(GatewayCursor, worker.stream_key).last_seq == 0


def test_loop_stops_and_records_stopped_state(components, session_factory):
    _, transport, worker = components
    stop = threading.Event()
    original = transport.poll

    def stopping(**kwargs):
        result = original(**kwargs)
        stop.set()
        return result

    transport.poll = stopping
    worker.run(stop)
    with session_factory() as session:
        assert session.get(GatewayCursor, worker.stream_key).state == "stopped"


def test_status_refuses_missing_and_stale_runtime(
    components, settings, db_engine, session_factory, capsys
):
    _, _, worker = components
    # CLI uses the selected Caspian channel, so use its matching stream.
    caspian_worker = GatewayWorker(
        session_factory,
        worker.runtime,
        worker.transport,
        channel="caspian:telegram",
        connection_id="connection-1",
    )
    configured = settings.model_copy(update={"caspian_telegram_connection_id": "connection-1"})
    with (
        patch("svaar.gateway.Settings", return_value=configured),
        patch("svaar.gateway.create_database_engine", return_value=db_engine),
    ):
        assert main(["--status"]) == 1
        caspian_worker._state("ready")
        assert main(["--status"]) == 0
        with session_factory() as session:
            session.get(GatewayCursor, caspian_worker.stream_key).heartbeat_at = datetime.now(
                UTC
            ) - timedelta(seconds=120)
            session.commit()
        assert main(["--status"]) == 1
    assert "stale" in capsys.readouterr().out
