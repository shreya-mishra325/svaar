"""Internal reference resolution with real PostgreSQL and a fake turn runner."""

import hashlib
import uuid

import pytest
from test_voice_notifications import setup_call

from svaar.voice.models import VoiceCall
from svaar.voice.references import ReferencedTurnRunner
from svaar.voice.runtime import REFUSAL

REFERENCE = "r" * 43


class Runner:
    def __init__(self):
        self.calls = []

    def run_turn(self, call_id, text, *, turn_index=None):
        self.calls.append((call_id, text, turn_index))
        return "synthetic-reply"


def prepare(sessions):
    _, _, identifier = setup_call(sessions)
    with sessions() as session:
        call = session.get(VoiceCall, identifier)
        call.call_ref_hash = hashlib.sha256(REFERENCE.encode()).hexdigest()
        call.execution_id = uuid.uuid4()
        call.provider_agent_id = uuid.uuid4()
        session.commit()
    return identifier


def test_reference_resolves_only_stored_call_id(session_factory):
    identifier = prepare(session_factory)
    runner = Runner()
    boundary = ReferencedTurnRunner(session_factory, runner)
    assert boundary.run_turn(REFERENCE, "hello", turn_index=0) == "synthetic-reply"
    assert runner.calls == [(str(identifier), "hello", 0)]
    assert boundary.run_turn("x" * 43, "hello", turn_index=0) == REFUSAL
    assert len(runner.calls) == 1
    with session_factory() as session:
        assert session.get(VoiceCall, identifier).call_ref_hash != REFERENCE


@pytest.mark.parametrize(
    "change", ["pending", "placing", "failed", "unknown", "execution", "agent", "hash"]
)
def test_unplaced_or_ineligible_calls_never_reach_runner(session_factory, change):
    identifier = prepare(session_factory)
    with session_factory() as session:
        call = session.get(VoiceCall, identifier)
        if change == "execution":
            call.execution_id = None
        elif change == "agent":
            call.provider_agent_id = None
        elif change == "hash":
            call.call_ref_hash = None
        else:
            call.state = change
        session.commit()
    runner = Runner()
    assert (
        ReferencedTurnRunner(session_factory, runner).run_turn(REFERENCE, "hello", turn_index=0)
        == REFUSAL
    )
    assert runner.calls == []


def test_first_authenticated_turn_activates_a_queued_placed_call(session_factory):
    # A provider receipt plus a resolvable reference proves placement; the turn
    # itself shows the call connected even if the in-progress callback is late.
    identifier = prepare(session_factory)
    with session_factory() as session:
        session.get(VoiceCall, identifier).state = "queued"
        session.commit()
    runner = Runner()
    reply = ReferencedTurnRunner(session_factory, runner).run_turn(REFERENCE, "hello", turn_index=0)
    assert reply != REFUSAL and len(runner.calls) == 1
    with session_factory() as session:
        assert session.get(VoiceCall, identifier).state == "active"


@pytest.mark.parametrize(
    "reference,text,index",
    [
        ("short", "hello", 0),
        ("x/" * 43, "hello", 0),
        (REFERENCE, "", 0),
        (REFERENCE, " ", 0),
        (REFERENCE, "x" * 20001, 0),
        (REFERENCE, "hello", None),
        (REFERENCE, "hello", True),
        (REFERENCE, "hello", -1),
        (REFERENCE, "hello", 2147483648),
    ],
)
def test_invalid_turn_inputs_refuse_without_database(settings, reference, text, index):
    def forbidden():
        pytest.fail("Invalid input reached database")

    runner = Runner()
    assert (
        ReferencedTurnRunner(forbidden, runner).run_turn(reference, text, turn_index=index)
        == REFUSAL
    )
    assert not runner.calls


def test_closed_call_delegates_retry_policy_to_guarded_runner(session_factory):
    identifier = prepare(session_factory)
    with session_factory() as session:
        session.get(VoiceCall, identifier).state = "closed"
        session.commit()
    runner = Runner()
    assert (
        ReferencedTurnRunner(session_factory, runner).run_turn(REFERENCE, "hello", turn_index=0)
        == "synthetic-reply"
    )
    assert runner.calls == [(str(identifier), "hello", 0)]


def test_resolved_reference_preserves_durable_retry_and_closed_call_guards(session_factory):
    from svaar.voice.runtime import VoiceRuntime

    identifier = prepare(session_factory)
    executions = []

    def execute(session, context, text, history):
        executions.append((context.principal_id, text))
        return "bounded-reply", "answered"

    boundary = ReferencedTurnRunner(session_factory, VoiceRuntime(session_factory, execute))
    assert boundary.run_turn(REFERENCE, "hello", turn_index=0) == "bounded-reply"
    assert boundary.run_turn(REFERENCE, "hello", turn_index=0) == "bounded-reply"
    assert boundary.run_turn(REFERENCE, "changed", turn_index=0) == REFUSAL
    assert boundary.run_turn(REFERENCE, "hello", turn_index=1) == "bounded-reply"
    assert len(executions) == 2
    with session_factory() as session:
        session.get(VoiceCall, identifier).state = "closed"
        session.commit()
    assert boundary.run_turn(REFERENCE, "hello", turn_index=1) == "bounded-reply"
    assert boundary.run_turn(REFERENCE, "hello", turn_index=2) == REFUSAL
    assert len(executions) == 2
