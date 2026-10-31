"""Bolna turn routes: bearer auth, OpenAI-compatible streaming and stable turn identity."""

import hashlib
import json
import secrets
import uuid
from datetime import timedelta

import pytest
from factories import make_org, make_principal
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from test_agent_loop import FakeEngine, FakeModel, proposal

from svaar.actions.catalog import build_registry
from svaar.actions.dispatcher import ApprovalPolicy, Dispatcher
from svaar.agent.llm import ModelReply
from svaar.agent.loop import AgentLoop
from svaar.agent.voice_runner import VoiceAgentExecutor
from svaar.app import create_app, create_status_ingress
from svaar.config import Settings
from svaar.decisions.service import DecisionService
from svaar.identity.models import ChannelBinding
from svaar.voice.models import VoiceCall, VoiceTurn
from svaar.voice.references import ReferencedTurnRunner
from svaar.voice.runtime import REFUSAL, VoiceRuntime

TOKEN = "t" * 32
AUTH = {"Authorization": "Bearer " + TOKEN}
REFERENCE = "r" * 43
LLM = "/api/v1/voice/llm/chat/completions"


def configured(mode="llm_endpoint", database_url="postgresql+psycopg://t:t@127.0.0.1:1/t", **extra):
    return Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        llm_base_url="https://llm.invalid/v1",
        llm_api_key="k",
        llm_model="test-model",
        voice_turn_mode=mode,
        voice_turn_token=TOKEN,
        **extra,
    )


class FakeRunner:
    def __init__(self, reply="Here is the timeline."):
        self.reply, self.turns, self.arrivals = reply, [], []

    def run_turn(self, reference, text, *, turn_index=None):
        self.turns.append((reference, text, turn_index))
        return self.reply

    def run_next(self, reference, text):
        self.arrivals.append((reference, text))
        return self.reply


@pytest.fixture
def runner():
    return FakeRunner()


def client_for(settings, runner, *, ingress=False):
    app = create_status_ingress(settings) if ingress else create_app(settings)
    client = TestClient(app, raise_server_exceptions=False)
    client.__enter__()
    app.state.voice_reference_runner = runner
    return client


def conversation(*users, reference=REFERENCE, final="user"):
    messages = [{"role": "system", "content": f"You are Svaar.\nsvaar_call_ref: {reference}"}]
    for index, text in enumerate(users):
        if index:
            messages.append({"role": "assistant", "content": f"answer {index}"})
        messages.append({"role": "user", "content": text})
    if final == "assistant":
        messages.append({"role": "assistant", "content": "done"})
    return {"model": "svaar", "messages": messages}


def stream_content(response):
    lines = [line for line in response.text.split("\n\n") if line]
    assert lines[-1] == "data: [DONE]"
    chunks = [json.loads(line.removeprefix("data: ")) for line in lines[:-1]]
    assert chunks[0]["choices"][0]["delta"] == {"role": "assistant"}
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    assert all(chunk["object"] == "chat.completion.chunk" for chunk in chunks)
    return "".join(chunk["choices"][0]["delta"].get("content", "") for chunk in chunks)


def test_streamed_turn_uses_history_index_and_replies_in_openai_format(runner):
    client = client_for(configured(), runner)
    try:
        body = {**conversation("hello", "what happened?"), "stream": True}
        response = client.post(LLM, json=body, headers=AUTH)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert stream_content(response) == "Here is the timeline."
        assert runner.turns == [(REFERENCE, "what happened?", 1)]
        # A retried request replays the same history, so it maps to the same turn.
        client.post(LLM, json=body, headers=AUTH)
        assert runner.turns[-1] == (REFERENCE, "what happened?", 1)
    finally:
        client.__exit__(None, None, None)


def test_non_streaming_completion_and_model_listing(runner):
    client = client_for(configured(), runner)
    try:
        response = client.post(LLM, json=conversation("hello"), headers=AUTH)
        choice = response.json()["choices"][0]
        assert choice["message"] == {"role": "assistant", "content": "Here is the timeline."}
        assert choice["finish_reason"] == "stop"
        models = client.get("/api/v1/voice/llm/models", headers=AUTH).json()
        assert models["data"][0]["id"] == "svaar"
    finally:
        client.__exit__(None, None, None)


@pytest.mark.parametrize(
    "body",
    [
        conversation("hello", reference="short"),
        conversation("hello", final="assistant"),
        {"messages": [{"role": "user", "content": "no marker"}]},
        {
            "messages": [
                {"role": "system", "content": f"svaar_call_ref: {REFERENCE}"},
                {"role": "system", "content": "svaar_call_ref: " + "z" * 43},
                {"role": "user", "content": "two references"},
            ]
        },
        conversation("   "),
    ],
)
def test_requests_without_one_trusted_reference_and_turn_fail_closed(runner, body):
    client = client_for(configured(), runner)
    try:
        response = client.post(LLM, json=body, headers=AUTH)
        assert response.json()["choices"][0]["message"]["content"] == REFUSAL
        assert runner.turns == []
    finally:
        client.__exit__(None, None, None)


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer " + "x" * 32}, {"Authorization": TOKEN}]
)
def test_wrong_or_missing_token_is_rejected(runner, headers):
    client = client_for(configured(), runner)
    try:
        assert client.post(LLM, json=conversation("hi"), headers=headers).status_code == 401
        assert client.get("/api/v1/voice/llm/models", headers=headers).status_code == 401
        assert runner.turns == []
    finally:
        client.__exit__(None, None, None)


def test_only_the_selected_mode_is_mounted(runner, settings):
    function = client_for(configured("function"), runner)
    try:
        assert function.post(LLM, json=conversation("hi"), headers=AUTH).status_code == 404
        reply = function.post(
            "/api/v1/voice/turn",
            json={"call_ref": REFERENCE, "utterance": "what happened?"},
            headers=AUTH,
        )
        assert reply.json() == {"reply": "Here is the timeline."}
        assert runner.arrivals == [(REFERENCE, "what happened?")]
    finally:
        function.__exit__(None, None, None)
    with TestClient(create_app(settings)) as unconfigured:
        assert unconfigured.post(LLM, json=conversation("hi"), headers=AUTH).status_code == 404
        assert unconfigured.post("/api/v1/voice/turn", json={}, headers=AUTH).status_code == 404


def test_restricted_tunnel_listener_serves_the_turn_route_only(runner):
    settings = configured(voice_status_secret="s" * 32)
    client = client_for(settings, runner, ingress=True)
    try:
        assert client.post(LLM, json=conversation("hi"), headers=AUTH).status_code == 200
        assert client.get("/docs").status_code == 404
        assert client.get("/health").status_code == 404
        assert client.post("/api/v1/orgs", json={}).status_code == 404
    finally:
        client.__exit__(None, None, None)


@pytest.mark.parametrize(
    "changes",
    [
        {"voice_turn_token": None},
        {"voice_turn_token": "short"},
        {"llm_base_url": None, "llm_api_key": None, "llm_model": None},
    ],
)
def test_turn_mode_requires_its_token_and_the_agent_model(changes):
    values = dict(
        _env_file=None,
        database_url="postgresql+psycopg://t:t@127.0.0.1:1/t",
        llm_base_url="https://llm.invalid/v1",
        llm_api_key="k",
        llm_model="test-model",
        voice_turn_mode="llm_endpoint",
        voice_turn_token=TOKEN,
    )
    values.update(changes)
    with pytest.raises(ValidationError):
        Settings(**values)


@pytest.fixture
def placed(session_factory):
    """A queued escalation call with a provider receipt and a private reference."""
    reference = secrets.token_urlsafe(32)
    with session_factory.begin() as session:
        org = make_org(session)
        person = make_principal(session, org, bindings=(("phone", "+15555550123"),))
        binding = session.scalar(select(ChannelBinding))
        call = VoiceCall(
            org_id=org.id,
            principal_id=person.id,
            phone_binding_id=binding.id,
            mission="escalation",
            state="queued",
            provider_status="queued",
            execution_id=uuid.uuid4(),
            provider_agent_id=uuid.uuid4(),
            call_ref_hash=hashlib.sha256(reference.encode()).hexdigest(),
        )
        session.add(call)
        session.flush()
        return reference, call.id


@pytest.mark.postgres
def test_first_authenticated_turn_activates_the_call_and_retries_replay(session_factory, placed):
    reference, call_id = placed
    model = FakeModel(proposal(), ModelReply("You are a team member."))
    loop = AgentLoop(
        model,
        Dispatcher(build_registry(), ApprovalPolicy(timedelta(minutes=10), 3, False)),
        DecisionService(FakeEngine(), high=0.85, low=0.55),
    )
    real = ReferencedTurnRunner(
        session_factory, VoiceRuntime(session_factory, VoiceAgentExecutor(loop))
    )
    client = client_for(configured(), real)
    try:
        body = conversation("who am I", reference=reference)
        first = client.post(LLM, json=body, headers=AUTH)
        again = client.post(LLM, json=body, headers=AUTH)
        for response in (first, again):
            assert response.json()["choices"][0]["message"]["content"] == "You are a team member."
        assert len(model.requests) == 2  # one tool round and one reply round, never repeated
        with session_factory() as session:
            assert session.get(VoiceCall, call_id).state == "active"
            assert [turn.turn_index for turn in session.scalars(select(VoiceTurn))] == [0]
        unknown = client.post(LLM, json=conversation("who am I"), headers=AUTH)
        assert unknown.json()["choices"][0]["message"]["content"] == REFUSAL
    finally:
        client.__exit__(None, None, None)
        loop.close()


@pytest.mark.postgres
def test_function_mode_sequences_arrivals(session_factory, placed):
    reference, call_id = placed
    model = FakeModel(ModelReply("First."), ModelReply("Second."))
    loop = AgentLoop(
        model,
        Dispatcher(build_registry(), ApprovalPolicy(timedelta(minutes=10), 3, False)),
        DecisionService(FakeEngine(), high=0.85, low=0.55),
    )
    real = ReferencedTurnRunner(
        session_factory, VoiceRuntime(session_factory, VoiceAgentExecutor(loop))
    )
    try:
        assert real.run_next(reference, "what happened?") == "First."
        assert real.run_next(reference, "and then?") == "Second."
        assert real.run_next("x" * 43, "unknown call") == REFUSAL
        with session_factory() as session:
            indices = sorted(t.turn_index for t in session.scalars(select(VoiceTurn)))
            assert indices == [0, 1]
    finally:
        loop.close()
