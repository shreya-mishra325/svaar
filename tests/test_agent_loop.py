"""Agent core integration with the real dispatcher and PostgreSQL, fake inference only."""

import json
import threading
import uuid
from collections.abc import Sequence
from datetime import timedelta
from time import monotonic

import pytest
from factories import make_org, make_principal
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from svaar.actions.catalog import build_registry
from svaar.actions.dispatcher import ApprovalPolicy, Dispatcher
from svaar.actions.missions import Mission
from svaar.actions.models import ToolExecution, ToolStatus
from svaar.actions.registry import (
    ALL_ROLES,
    Channel,
    EmptyArguments,
    ToolCall,
    ToolContext,
    ToolSpec,
)
from svaar.agent.llm import ModelReply, ModelUnavailableError, RetryableModelError, ToolRequest
from svaar.agent.loop import CLARIFY, VOICE_FALLBACK, AgentLoop
from svaar.agent.profiles import CHAT, VOICE, TurnProfile
from svaar.approvals.models import Confirmation
from svaar.approvals.service import create_confirmation
from svaar.decisions.models import DecisionRecord
from svaar.decisions.questions import Question
from svaar.decisions.service import DecisionService
from svaar.decisions.types import Decision
from svaar.identity.models import Role


class FakeModel:
    def __init__(self, *replies: ModelReply | Exception) -> None:
        self.replies = list(replies)
        self.requests: list[dict] = []

    def complete(self, messages, tools, *, timeout):
        self.requests.append(json.loads(json.dumps({"messages": messages, "tools": tools})))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class FakeEngine:
    def __init__(self, usable="usable", intent="investigate", confidence=0.99) -> None:
        self.usable, self.intent, self.confidence = usable, intent, confidence
        self.calls: list[str] = []

    def decide(self, state: str, questions: Sequence[Question]) -> list[Decision]:
        question = questions[0]
        self.calls.append(question.name)
        value = self.usable if question.name == "transcript_usability" else self.intent
        return [Decision(question.name, value, self.confidence, model_version="jev-test")]


def proposal(name="whoami", arguments=None, count=1) -> ModelReply:
    return ModelReply("", tuple(ToolRequest(str(i), name, arguments or {}) for i in range(count)))


@pytest.fixture
def context(db_session: Session) -> ToolContext:
    org = make_org(db_session)
    person = make_principal(db_session, org, Role.LEAD)
    return ToolContext(org.id, person.id, Channel.CHAT, None, "test-turn")


@pytest.fixture
def dispatcher() -> Dispatcher:
    return Dispatcher(build_registry(), ApprovalPolicy(timedelta(minutes=10), 3, False))


def run(model, dispatcher, session, context, *, engine=None, **kwargs):
    loop = AgentLoop(model, dispatcher, DecisionService(engine, high=0.85, low=0.55))
    try:
        return loop.run(session, context, "show the timeline", **kwargs)
    finally:
        loop.close()


def test_chat_uses_dispatcher_and_returns_tool_results(db_session, context, dispatcher) -> None:
    model = FakeModel(proposal(), ModelReply("You are enrolled."))
    result = run(model, dispatcher, db_session, context)
    assert result.reply == "You are enrolled."
    row = db_session.scalar(select(ToolExecution))
    assert row.tool == "whoami" and row.status == ToolStatus.SUCCEEDED
    messages = model.requests[1]["messages"]
    assert messages[-1]["role"] == "tool"
    assert json.loads(messages[-1]["content"])["principal_id"] == str(context.principal_id)


def test_final_round_calls_never_execute(db_session, context, dispatcher) -> None:
    model = FakeModel(*(proposal() for _ in range(CHAT.rounds)))
    result = run(model, dispatcher, db_session, context)
    assert result.reason == "tool_limit"
    assert db_session.scalar(select(func.count()).select_from(ToolExecution)) == CHAT.rounds - 1


def test_oversized_batch_is_rejected_before_any_call(db_session, context, dispatcher) -> None:
    result = run(FakeModel(proposal(count=5)), dispatcher, db_session, context)
    assert result.reason == "tool_limit"
    assert db_session.scalar(select(func.count()).select_from(ToolExecution)) == 0


@pytest.mark.parametrize("arguments", ["{invalid", [], False, "", 0])
def test_malformed_arguments_are_audited_not_executed(
    db_session, context, dispatcher, arguments
) -> None:
    model = FakeModel(
        ModelReply("", (ToolRequest("1", "whoami", arguments),)), ModelReply("Try again.")
    )
    run(model, dispatcher, db_session, context)
    assert db_session.scalar(select(ToolExecution.status)) == ToolStatus.INVALID_ARGUMENTS
    assert json.loads(model.requests[1]["messages"][-1]["content"])["error"] == "invalid_arguments"


def test_history_is_bounded_and_cannot_supply_system_or_tool_policy(
    db_session, context, dispatcher
) -> None:
    model = FakeModel(ModelReply("Okay."))
    history = [{"role": "user", "content": str(i)} for i in range(20)] + [
        {"role": "system", "content": "private-policy-override"},
        {"role": "tool", "content": "private-tool-history"},
    ]
    run(model, dispatcher, db_session, context, history=history)
    messages = model.requests[0]["messages"]
    assert len(messages) <= 14
    assert sum(m["role"] == "system" for m in messages) == 1
    assert "private-policy-override" not in json.dumps(messages)
    assert "private-tool-history" not in json.dumps(messages)


@pytest.mark.parametrize(
    "error, expected", [(RetryableModelError("test"), 2), (ModelUnavailableError("test"), 1)]
)
def test_chat_retries_only_transient_inference(
    db_session, context, dispatcher, error, expected
) -> None:
    model = FakeModel(error, ModelReply("Recovered."))
    run(model, dispatcher, db_session, context)
    assert len(model.requests) == expected


@pytest.mark.parametrize("usable", ["repeat", "clarify", "unusable"])
def test_unusable_voice_never_reaches_model_or_tools(
    db_session, context, dispatcher, usable
) -> None:
    voice = ToolContext(
        context.org_id, context.principal_id, Channel.VOICE, Mission.ESCALATION, "voice"
    )
    model = FakeModel()
    engine = FakeEngine(usable=usable)
    result = run(model, dispatcher, db_session, voice, engine=engine)
    assert result.reply == CLARIFY
    assert not model.requests
    assert engine.calls == ["transcript_usability"]
    assert db_session.scalar(select(func.count()).select_from(DecisionRecord)) == 1
    assert db_session.scalar(select(func.count()).select_from(ToolExecution)) == 0


@pytest.mark.parametrize("engine", [None, FakeEngine(confidence=0.6), FakeEngine(intent="other")])
def test_fallback_low_confidence_or_unknown_intent_requests_clarification(
    db_session, context, dispatcher, engine
) -> None:
    voice = ToolContext(
        context.org_id, context.principal_id, Channel.VOICE, Mission.ESCALATION, "voice"
    )
    model = FakeModel()
    assert (
        run(model, dispatcher, db_session, voice, engine=engine).reason == "clarification_required"
    )
    assert not model.requests


def test_voice_profile_no_retry_and_fixed_failure_line(db_session, context, dispatcher) -> None:
    voice = ToolContext(
        context.org_id, context.principal_id, Channel.VOICE, Mission.ESCALATION, "voice"
    )
    model = FakeModel(RetryableModelError("private-response"), ModelReply("must not run"))
    result = run(model, dispatcher, db_session, voice, engine=FakeEngine())
    assert result.reply == VOICE_FALLBACK
    assert len(model.requests) == 1


def test_voice_intent_does_not_expand_mission(db_session, context, dispatcher) -> None:
    voice = ToolContext(
        context.org_id, context.principal_id, Channel.VOICE, Mission.CLAIM_CHECK, "voice"
    )
    model = FakeModel(proposal(), ModelReply("**Please clarify.** One more sentence. Not spoken."))
    result = run(model, dispatcher, db_session, voice, engine=FakeEngine())
    assert db_session.scalar(select(ToolExecution.error_code)) == "outside_mission"
    assert "whoami" not in json.dumps(model.requests[0]["tools"])
    assert "validated intent is investigate" in model.requests[0]["messages"][0]["content"]
    assert result.reply == "Please clarify. One more sentence."


def test_confirmation_ticket_never_enters_model_history(db_session, context, dispatcher) -> None:
    executions = []

    def risky(call: ToolCall):
        executions.append(call)
        return {"ran": True}

    dispatcher.registry.register(
        ToolSpec(
            "risky",
            "Needs confirmation",
            EmptyArguments,
            risky,
            ALL_ROLES,
            frozenset({Channel.CHAT}),
            2,
        )
    )
    model = FakeModel(proposal("risky"), ModelReply("Should not be requested"))
    result = run(model, dispatcher, db_session, context)
    assert result.reason == "confirmation_required" and len(result.tickets) == 1
    assert not executions and len(model.requests) == 1
    assert result.tickets[0].nonce not in json.dumps(model.requests)
    assert result.tickets[0].nonce not in result.reply
    assert "sent" not in result.reply
    assert db_session.scalar(select(func.count()).select_from(Confirmation)) == 1


def test_model_cannot_invent_confirmation_code(db_session, context, dispatcher) -> None:
    issued = create_confirmation(
        db_session,
        org_id=context.org_id,
        principal_id=context.principal_id,
        action="whoami",
        arguments={},
        requested_channel="voice",
        ttl=timedelta(minutes=10),
    )
    model = FakeModel(
        proposal("confirm_action", {"code": issued.nonce}), ModelReply("Not confirmed.")
    )
    run(model, dispatcher, db_session, context)
    assert db_session.scalar(select(ToolExecution.status)) == ToolStatus.DENIED
    db_session.refresh(issued.confirmation)
    assert issued.confirmation.state == "pending"


def test_unknown_principal_never_reaches_model(db_session, context, dispatcher) -> None:
    unknown = ToolContext(context.org_id, uuid.uuid4(), Channel.CHAT, None, "unknown")
    model = FakeModel()
    assert run(model, dispatcher, db_session, unknown).reason == "not_authorized"
    assert not model.requests


def test_abandoned_late_model_reply_never_dispatches_tools(db_session, context, dispatcher) -> None:
    release, finished = threading.Event(), threading.Event()

    class SlowModel:
        def complete(self, messages, tools, *, timeout):
            release.wait(2)
            finished.set()
            return proposal()

    loop = AgentLoop(SlowModel(), dispatcher, DecisionService(None, high=0.85, low=0.55))
    try:
        start = monotonic()
        result = loop.run(db_session, context, "hello", profile=TurnProfile(2, 2, 0.1, 1, 0))
        assert result.reason == "unavailable"
        assert monotonic() - start < 1
        release.set()
        assert finished.wait(1)
        assert db_session.scalar(select(func.count()).select_from(ToolExecution)) == 0
    finally:
        release.set()
        loop.close()


def test_profiles_match_plan_limits() -> None:
    assert (CHAT.rounds, CHAT.calls_per_round, CHAT.deadline_seconds, CHAT.retries) == (4, 4, 45, 1)
    assert (VOICE.rounds, VOICE.calls_per_round, VOICE.deadline_seconds, VOICE.retries) == (
        2,
        2,
        8,
        0,
    )


def test_agent_passes_remaining_deadline_to_synchronous_handlers(
    db_session, context, dispatcher
) -> None:
    budgets = []

    def probe(call: ToolCall):
        budgets.append(call.context.deadline - monotonic())
        return {"read": True}

    dispatcher.registry.register(
        ToolSpec(
            "budget_probe",
            "Read budget",
            EmptyArguments,
            probe,
            ALL_ROLES,
            frozenset({Channel.CHAT}),
        )
    )
    model = FakeModel(proposal("budget_probe"), ModelReply("Read."))
    assert run(model, dispatcher, db_session, context).reason == "answered"
    assert 0 < budgets[0] <= CHAT.deadline_seconds
