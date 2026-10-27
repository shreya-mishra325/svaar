"""Structured classifier and single-request voice gates with fake inference only."""

import json
import threading
from time import monotonic

import httpx
import pytest
from factories import make_org, make_principal
from pydantic import SecretStr, ValidationError
from sqlalchemy import func, select
from test_agent_loop import FakeModel, proposal

from svaar.actions.catalog import build_registry
from svaar.actions.dispatcher import ApprovalPolicy, Dispatcher
from svaar.actions.missions import Mission
from svaar.actions.models import ToolExecution
from svaar.actions.registry import Channel, ToolContext
from svaar.agent.llm import HttpChatModel, ModelReply
from svaar.agent.loop import AgentLoop
from svaar.agent.profiles import TurnProfile
from svaar.config import Settings
from svaar.decisions.classifier import StructuredClassifier
from svaar.decisions.models import DecisionRecord
from svaar.decisions.questions import TRANSCRIPT_USABILITY, VOICE_INTENT
from svaar.decisions.service import DecisionService
from svaar.decisions.types import DecisionSource, DecisionUnavailableError

QUESTIONS = [TRANSCRIPT_USABILITY, VOICE_INTENT]


def response(*, confidence=0.99, intent="investigate"):
    return json.dumps(
        {
            "answers": {
                "transcript_usability": {"label": "usable", "confidence": confidence},
                "voice_intent": {"label": intent, "confidence": confidence},
            }
        }
    )


class Generate:
    def __init__(self, raw):
        self.raw = raw
        self.calls = []

    def __call__(self, messages, *, timeout):
        self.calls.append((messages, timeout))
        if isinstance(self.raw, Exception):
            raise self.raw
        return self.raw


def test_grouped_classifier_is_one_request_with_no_fabricated_probabilities():
    generate = Generate(response())
    engine = StructuredClassifier(generate, model_version="test")
    answers = engine.decide("show the timeline", QUESTIONS)
    assert len(generate.calls) == 1 and len(answers) == 2
    assert all(answer.source is DecisionSource.MODEL for answer in answers)
    assert all(answer.probabilities == {} for answer in answers)
    assert generate.calls[0][1] == 6


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        "null",
        '{"answers":[]}',
        '{"answers":{}} extra',
        "x" * 65537,
        '{"answers":{},"extra":true}',
        '{"answers":{},"answers":{}}',
        RuntimeError("private-provider-detail"),
    ],
)
def test_invalid_envelopes_fail_safely(raw):
    generate = Generate(raw)
    with pytest.raises(DecisionUnavailableError) as exc:
        StructuredClassifier(generate, model_version="test").decide("text", QUESTIONS)
    assert "private" not in str(exc.value)
    assert len(generate.calls) == 1


@pytest.mark.parametrize(
    "answer",
    [
        {"label": "invented", "confidence": 0.99},
        {"label": "investigate", "confidence": True},
        {"label": "investigate", "confidence": "0.99"},
        {"label": "investigate", "confidence": float("nan")},
        {"label": "investigate", "confidence": float("inf")},
        {"label": "investigate", "confidence": -1},
        {"label": "investigate", "confidence": 10**400},
        {"label": "investigate"},
        {"label": "investigate", "confidence": 0.99, "reason": "extra"},
    ],
)
def test_bad_slot_preserves_valid_slot(answer):
    body = json.loads(response())
    body["answers"]["voice_intent"] = answer
    engine = StructuredClassifier(Generate(json.dumps(body)), model_version="test")
    answers = engine.decide("text", QUESTIONS)
    assert [answer.name for answer in answers] == ["transcript_usability"]


def test_duplicate_key_invalidates_only_its_slot():
    raw = (
        '{"answers":{"transcript_usability":{"label":"usable","confidence":0.99},'
        '"voice_intent":{"label":"investigate","label":"other","confidence":0.99}}}'
    )
    answers = StructuredClassifier(Generate(raw), model_version="test").decide("text", QUESTIONS)
    assert [answer.name for answer in answers] == ["transcript_usability"]


def test_chat_adapter_reuses_credentials_and_sends_no_tools():
    requests = []

    def handle(request):
        requests.append(request)
        body = json.loads(request.content)
        assert request.headers["Authorization"] == "Bearer synthetic-key"
        assert body["model"] == "test" and "tools" not in body
        return httpx.Response(200, json={"choices": [{"message": {"content": response()}}]})

    model = HttpChatModel(
        base_url="https://example.invalid/v1",
        api_key=SecretStr("synthetic-key"),
        model="test",
        transport=httpx.MockTransport(handle),
    )
    try:
        result = StructuredClassifier(model.classify, model_version="test").decide(
            "text", QUESTIONS
        )
        assert len(result) == 2 and len(requests) == 1
    finally:
        model.close()


def test_classifier_tool_proposals_are_never_executed():
    model = HttpChatModel(
        base_url="https://example.invalid/v1",
        api_key=SecretStr("synthetic-key"),
        model="test",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "1",
                                        "type": "function",
                                        "function": {"name": "whoami", "arguments": "{}"},
                                    }
                                ],
                            }
                        }
                    ]
                },
            )
        ),
    )
    try:
        with pytest.raises(DecisionUnavailableError):
            StructuredClassifier(model.classify, model_version="test").decide("text", QUESTIONS)
    finally:
        model.close()


def setup(session):
    org = make_org(session)
    person = make_principal(session, org)
    return ToolContext(org.id, person.id, Channel.VOICE, Mission.ESCALATION, "classifier-test")


def loop(model, generate):
    return AgentLoop(
        model,
        Dispatcher(
            build_registry(),
            ApprovalPolicy.from_settings(
                Settings(
                    _env_file=None,
                    database_url="postgresql+psycopg://test:test@127.0.0.1:1/test",
                )
            ),
        ),
        DecisionService(StructuredClassifier(generate, model_version="test"), high=0.85, low=0.55),
    )


def test_grouped_voice_gate_reaches_dispatcher_once(db_session):
    context = setup(db_session)
    generate = Generate(response())
    model = FakeModel(proposal(), ModelReply("You are enrolled."))
    agent = loop(model, generate)
    try:
        assert agent.run(db_session, context, "show the timeline").reason == "answered"
        assert len(generate.calls) == 1 and len(model.requests) == 2
        assert db_session.scalar(select(func.count()).select_from(ToolExecution)) == 1
        rows = db_session.scalars(select(DecisionRecord)).all()
        assert len(rows) == 2 and {row.source for row in rows} == {"model"}
    finally:
        agent.close()


def test_one_invalid_slot_defers_without_discarding_valid_audit(db_session):
    context = setup(db_session)
    generate = Generate(response(intent="invented"))
    model = FakeModel()
    agent = loop(model, generate)
    try:
        assert (
            agent.run(db_session, context, "show the timeline").reason == "clarification_required"
        )
        rows = {row.question: row for row in db_session.scalars(select(DecisionRecord))}
        assert rows["transcript_usability"].source == "model"
        assert rows["voice_intent"].source == "fallback"
        assert rows["voice_intent"].fallback_reason == "missing_answer"
        assert not model.requests and len(generate.calls) == 1
    finally:
        agent.close()


@pytest.mark.parametrize("text", ["", "...", "hello"])
def test_heuristic_precheck_does_not_spend_classifier_request(db_session, text):
    context = setup(db_session)
    generate = Generate(response())
    agent = loop(FakeModel(), generate)
    try:
        assert agent.run(db_session, context, text).reason == "clarification_required"
        assert not generate.calls
        assert db_session.scalar(select(DecisionRecord.source)) == "fallback"
    finally:
        agent.close()


def test_late_classifier_never_reaches_reply_model_or_tools(db_session):
    context = setup(db_session)
    release, finished = threading.Event(), threading.Event()
    budgets = []

    def generate(messages, *, timeout):
        budgets.append(timeout)
        release.wait(2)
        finished.set()
        return response()

    model = FakeModel()
    agent = loop(model, generate)
    try:
        started = monotonic()
        result = agent.run(
            db_session, context, "show the timeline", profile=TurnProfile(2, 2, 0.1, 1, 0)
        )
        assert result.reason == "unavailable" and monotonic() - started < 1
        assert 0 < budgets[0] <= 0.1
        release.set()
        assert finished.wait(1)
        assert not model.requests
        assert db_session.scalar(select(func.count()).select_from(ToolExecution)) == 0
    finally:
        release.set()
        agent.close()


def test_classifier_opt_in_requires_existing_llm_configuration(settings):
    assert not settings.classifier_enabled
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=settings.database_url, classifier_enabled=True)


def test_historical_provider_audit_rows_are_not_rewritten(db_session):
    context = setup(db_session)
    historical = DecisionRecord(
        org_id=context.org_id,
        state_hash="a" * 64,
        question="historic",
        answer="other",
        confidence=0.9,
        model_version="retired-provider",
        source="jev",
        policy_outcome="defer",
    )
    db_session.add(historical)
    db_session.flush()
    identifier = historical.id
    service = DecisionService(
        StructuredClassifier(Generate(response()), model_version="current-model"),
        high=0.85,
        low=0.55,
    )
    service.decide(
        db_session, org_id=context.org_id, state="show the timeline", questions=QUESTIONS
    )
    db_session.expire_all()
    assert db_session.get(DecisionRecord, identifier).source == "jev"
    assert {
        row.source
        for row in db_session.scalars(select(DecisionRecord).where(DecisionRecord.id != identifier))
    } == {"model"}


def test_six_digit_code_is_usable_but_fallback_still_defers():
    from svaar.decisions.fallback import HeuristicEngine
    from svaar.decisions.policy import PolicyOutcome, evaluate

    answer = HeuristicEngine().answer("001234", TRANSCRIPT_USABILITY)
    assert answer.value == "usable" and answer.confidence == 0
    assert evaluate(answer, TRANSCRIPT_USABILITY, high=0.85, low=0.55) is PolicyOutcome.DEFER
