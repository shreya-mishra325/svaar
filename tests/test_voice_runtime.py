"""Durable voice turns use real gates and PostgreSQL, with fake inference only."""

import threading
import uuid
from datetime import timedelta

import pytest
from factories import make_org, make_principal
from sqlalchemy import func, select
from test_agent_loop import FakeEngine, FakeModel, proposal

from svaar.actions.catalog import build_registry
from svaar.actions.dispatcher import ApprovalPolicy, Dispatcher
from svaar.actions.models import ToolExecution
from svaar.agent.llm import ModelReply, ModelUnavailableError
from svaar.agent.loop import CLARIFY, AgentLoop
from svaar.agent.voice_runner import VoiceAgentExecutor
from svaar.decisions.service import DecisionService
from svaar.identity.models import ChannelBinding
from svaar.voice.models import VoiceCall, VoiceTurn
from svaar.voice.runtime import FALLBACK, REFUSAL, VoiceRuntime


@pytest.fixture
def call_id(session_factory):
    with session_factory() as session:
        org = make_org(session)
        person = make_principal(session, org, bindings=(("phone", "+15555550123"),))
        binding = session.scalar(select(ChannelBinding))
        call = VoiceCall(
            org_id=org.id,
            principal_id=person.id,
            phone_binding_id=binding.id,
            mission="escalation",
            state="active",
        )
        session.add(call)
        session.commit()
        return str(call.id)


def build(sessions, model, engine=None):
    loop = AgentLoop(
        model,
        Dispatcher(build_registry(), ApprovalPolicy(timedelta(minutes=10), 3, False)),
        DecisionService(engine, high=0.85, low=0.55),
    )
    return VoiceRuntime(sessions, VoiceAgentExecutor(loop)), loop


def test_shared_dispatcher_dedupe_and_history(session_factory, call_id):
    model = FakeModel(proposal(), ModelReply("You are enrolled."), ModelReply("Again."))
    runtime, loop = build(session_factory, model, FakeEngine())
    try:
        assert runtime.run_turn(call_id, "who am I", turn_index=0) == "You are enrolled."
        assert runtime.run_turn(call_id, "who am I", turn_index=0) == "You are enrolled."
        assert runtime.run_turn(call_id, "changed", turn_index=0) == REFUSAL
        assert runtime.run_turn(call_id, "who am I", turn_index=1) == "Again."
        assert len(model.requests) == 3
        history = model.requests[-1]["messages"]
        assert history[-2] == {"role": "assistant", "content": "You are enrolled."}
        with session_factory() as session:
            assert session.scalar(select(func.count()).select_from(ToolExecution)) == 1
            assert session.scalar(select(func.count()).select_from(VoiceTurn)) == 2
    finally:
        loop.close()


@pytest.mark.parametrize("invalid", [None, -1, True, 1, 2147483648])
def test_missing_or_invalid_index_never_executes(session_factory, call_id, invalid):
    model = FakeModel()
    runtime, loop = build(session_factory, model, FakeEngine())
    try:
        assert runtime.run_turn(call_id, "hello", turn_index=invalid) == REFUSAL
        assert not model.requests
    finally:
        loop.close()


@pytest.mark.parametrize(
    "change", ["unknown", "closed", "unverified", "wrong_org", "wrong_owner", "wrong_channel"]
)
def test_untrusted_call_context_never_executes(session_factory, call_id, change):
    with session_factory() as session:
        call = session.get(VoiceCall, uuid.UUID(call_id))
        binding = session.get(ChannelBinding, call.phone_binding_id)
        if change == "closed":
            call.state = "closed"
        elif change == "unverified":
            binding.verified_at = None
        elif change == "wrong_org":
            call.org_id = make_org(session, "Other").id
        elif change == "wrong_owner":
            binding.principal_id = make_principal(session, make_org(session, "Other")).id
        elif change == "wrong_channel":
            binding.channel = "chat"
        session.commit()
    model = FakeModel()
    runtime, loop = build(session_factory, model, FakeEngine())
    try:
        assert (
            runtime.run_turn(
                str(uuid.uuid4()) if change == "unknown" else call_id, "hello", turn_index=0
            )
            == REFUSAL
        )
        assert not model.requests
    finally:
        loop.close()


@pytest.mark.parametrize("engine", [None, FakeEngine(usable="unusable")])
def test_unusable_speech_has_saved_clarification_without_tools(session_factory, call_id, engine):
    model = FakeModel()
    runtime, loop = build(session_factory, model, engine)
    try:
        assert runtime.run_turn(call_id, "unclear", turn_index=0) == CLARIFY
        assert runtime.run_turn(call_id, "unclear", turn_index=0) == CLARIFY
        assert not model.requests
        with session_factory() as session:
            assert session.scalar(select(VoiceTurn.user_text)) == "[unavailable or unclear input]"
            assert session.scalar(select(func.count()).select_from(ToolExecution)) == 0
    finally:
        loop.close()


def test_mission_never_expands_from_intent(session_factory, call_id):
    with session_factory() as session:
        session.get(VoiceCall, uuid.UUID(call_id)).mission = "confirmation"
        session.commit()
    model = FakeModel(proposal(), ModelReply("Please clarify."))
    runtime, loop = build(session_factory, model, FakeEngine())
    try:
        runtime.run_turn(call_id, "who am I", turn_index=0)
        with session_factory() as session:
            assert session.scalar(select(ToolExecution.error_code)) == "outside_mission"
    finally:
        loop.close()


def test_model_failure_persists_fixed_reply_without_retry(session_factory, call_id):
    model = FakeModel(ModelUnavailableError("private"))
    runtime, loop = build(session_factory, model, FakeEngine())
    try:
        assert runtime.run_turn(call_id, "show the timeline", turn_index=0) == FALLBACK
        assert runtime.run_turn(call_id, "show the timeline", turn_index=0) == FALLBACK
        assert len(model.requests) == 1
    finally:
        loop.close()


def test_crash_after_committed_effect_never_replays(session_factory, call_id):
    calls = []

    def crash(session, context, text, history):
        calls.append(context)
        session.commit()
        raise RuntimeError("private")

    runtime = VoiceRuntime(session_factory, crash)
    assert runtime.run_turn(call_id, "hello", turn_index=0) == FALLBACK
    assert runtime.run_turn(call_id, "hello", turn_index=0) == FALLBACK
    assert runtime.run_turn(call_id, "next", turn_index=1) == FALLBACK
    assert len(calls) == 1
    with session_factory() as session:
        assert session.scalar(select(VoiceTurn.state)) == "unknown"


def test_process_interruption_leaves_marker(session_factory, call_id):
    def crash(*args):
        raise KeyboardInterrupt()

    runtime = VoiceRuntime(session_factory, crash)
    with pytest.raises(KeyboardInterrupt):
        runtime.run_turn(call_id, "hello", turn_index=0)
    assert runtime.run_turn(call_id, "hello", turn_index=0) == FALLBACK
    with session_factory() as session:
        assert session.scalar(select(VoiceTurn.state)) == "processing"


def test_concurrent_call_lock_survives_executor_commit(session_factory, call_id):
    started, release = threading.Event(), threading.Event()

    def execute(session, context, text, history):
        session.commit()
        started.set()
        assert release.wait(3)
        return "Done.", "answered"

    runtime = VoiceRuntime(session_factory, execute)
    results = []
    thread = threading.Thread(
        target=lambda: results.append(runtime.run_turn(call_id, "hello", turn_index=0))
    )
    thread.start()
    try:
        assert started.wait(2)
        assert runtime.run_turn(call_id, "hello", turn_index=0) == FALLBACK
    finally:
        release.set()
        thread.join(3)
    assert results == ["Done."]


def test_history_scoped_and_confirmation_input_redacted(session_factory, call_id):
    histories = []

    def execute(session, context, text, history):
        histories.append(history)
        return "Okay.", "answered"

    runtime = VoiceRuntime(session_factory, execute)
    runtime.run_turn(call_id, "123456", turn_index=0)
    runtime.run_turn(call_id, "next", turn_index=1)
    assert histories[-1][0]["content"] == "[confirmation input]"
    with session_factory() as session:
        original = session.get(VoiceCall, uuid.UUID(call_id))
        other = VoiceCall(
            org_id=original.org_id,
            principal_id=original.principal_id,
            phone_binding_id=original.phone_binding_id,
            mission="escalation",
            state="active",
        )
        session.add(other)
        session.commit()
        second = str(other.id)
    runtime.run_turn(second, "hello", turn_index=0)
    assert histories[-1] == []
