"""Offline Jev HTTP, policy and audit checks. No credentials or provider requests."""

import json

import httpx
import pytest
from factories import make_org
from pydantic import SecretStr
from sqlalchemy import select

from svaar.decisions.jev import VercelJevEngine
from svaar.decisions.models import DecisionRecord
from svaar.decisions.policy import PolicyOutcome
from svaar.decisions.questions import TRANSCRIPT_USABILITY, VOICE_INTENT
from svaar.decisions.service import DecisionService
from svaar.decisions.types import DecisionUnavailableError

MODEL = "typesafe-ai/jev-1.13.0"
QUESTIONS = (TRANSCRIPT_USABILITY, VOICE_INTENT)


def answer(question, label, confidence=0.95):
    return {
        "type": "choice",
        "choice": label,
        "confidence": confidence,
        "probabilities": {value: float(value == label) for value in question.labels},
    }


def envelope(**answers):
    return {"model": MODEL, "answers": answers}


def engine(handler):
    return VercelJevEngine(
        api_key=SecretStr("offline-test-key"),
        model=MODEL,
        transport=httpx.MockTransport(handler),
    )


def test_gateway_request_uses_native_shape_and_pinned_model():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=envelope(voice_intent=answer(VOICE_INTENT, "investigate")))

    adapter = engine(respond)
    try:
        result = adapter.decide("show the timeline", [VOICE_INTENT])
        assert result[0].value == "investigate" and result[0].model_version == MODEL
        request = requests[0]
        assert str(request.url) == "https://ai-gateway.vercel.sh/typesafe/v1/systemone"
        assert request.headers["authorization"] == "Bearer offline-test-key"
        payload = json.loads(request.content)
        assert payload["model"] == MODEL and payload["state"] == "show the timeline"
        assert payload["questions"]["voice_intent"]["criteria"] == VOICE_INTENT.criteria
        assert "instructions" in payload["questions"]["voice_intent"]
        assert "providerOptions" not in payload
        assert request.extensions["timeout"]["read"] == 2.0
    finally:
        adapter.close()
    assert adapter._client.is_closed


@pytest.mark.parametrize("status", [302, 401, 402, 429, 500, 503])
def test_http_errors_are_sanitized_without_retry(status):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, text="private-provider-payload")

    adapter = engine(respond)
    try:
        with pytest.raises(DecisionUnavailableError) as error:
            adapter.decide("private-state", QUESTIONS)
        assert len(requests) == 1
        assert "private" not in str(error.value)
        assert error.value.__cause__ is None
    finally:
        adapter.close()


@pytest.mark.parametrize("body", [None, [], {}, {"model": MODEL, "answers": []}])
def test_malformed_envelopes_fail_closed(body):
    adapter = engine(lambda _: httpx.Response(200, json=body))
    try:
        with pytest.raises(DecisionUnavailableError):
            adapter.decide("state", QUESTIONS)
    finally:
        adapter.close()


@pytest.mark.parametrize(
    "override",
    [
        {"confidence": None},
        {"confidence": True},
        {"confidence": "0.99"},
        {"confidence": 1.01},
        {"choice": "rerun_now"},
        {"type": "noul"},
        {"probabilities": {}},
        {"probabilities": {"investigate": 1.0}},
        {"probabilities": dict.fromkeys(VOICE_INTENT.labels, 0.0)},
        {"probabilities": dict.fromkeys(VOICE_INTENT.labels, True)},
    ],
)
def test_invalid_sibling_does_not_discard_valid_answer(override):
    bad = answer(VOICE_INTENT, "investigate") | override
    adapter = engine(
        lambda _: httpx.Response(
            200,
            json=envelope(
                transcript_usability=answer(TRANSCRIPT_USABILITY, "usable"), voice_intent=bad
            ),
        )
    )
    try:
        results = adapter.decide("state", QUESTIONS)
        assert [result.name for result in results] == ["transcript_usability"]
    finally:
        adapter.close()


def test_model_mismatch_is_not_recorded_as_the_requested_version():
    adapter = engine(lambda _: httpx.Response(200, json={"model": "other", "answers": {}}))
    try:
        with pytest.raises(DecisionUnavailableError):
            adapter.decide("state", QUESTIONS)
    finally:
        adapter.close()


@pytest.mark.postgres
@pytest.mark.parametrize("scenario", ["success", "low_confidence", "partial", "timeout"])
def test_mocked_gateway_policy_and_per_question_database_audit(db_session, scenario):
    requests = []

    def respond(request):
        requests.append(request)
        if scenario == "timeout":
            raise httpx.ReadTimeout("private-state", request=request)
        confidence = 0.6 if scenario == "low_confidence" else 0.95
        intent = answer(VOICE_INTENT, "investigate", confidence)
        if scenario == "partial":
            intent.pop("confidence")
        return httpx.Response(
            200,
            json=envelope(
                transcript_usability=answer(TRANSCRIPT_USABILITY, "usable"), voice_intent=intent
            ),
        )

    adapter = engine(respond)
    try:
        org = make_org(db_session)
        results = DecisionService(adapter, high=0.85, low=0.55).decide(
            db_session,
            org_id=org.id,
            state="show the timeline; contact demo@example.com",
            questions=QUESTIONS,
        )
        assert b"demo@example.com" not in requests[0].content
        rows = db_session.scalars(select(DecisionRecord)).all()
        assert len(rows) == 2
        if scenario == "timeout":
            assert all(result.outcome is PolicyOutcome.DEFER for result in results)
            assert {row.fallback_reason for row in rows} == {"engine_unavailable"}
        elif scenario == "partial":
            assert results[0].outcome is PolicyOutcome.ACT
            assert results[1].outcome is PolicyOutcome.DEFER
            assert results[1].decision.confidence == 0.0
        else:
            expected = PolicyOutcome.ASK if scenario == "low_confidence" else PolicyOutcome.ACT
            assert results[1].outcome is expected
            assert all(row.model_version == MODEL for row in rows)
    finally:
        adapter.close()
