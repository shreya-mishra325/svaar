"""Verified REST shapes exercised entirely with synthetic HTTP responses."""

import json
import uuid

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from svaar.config import Settings
from svaar.voice.bolna import BolnaClient
from svaar.voice.provider import (
    CallOutcomeUnknownError,
    CallRejectedError,
    VoiceProviderUnavailableError,
)

AGENT = uuid.UUID("123e4567-e89b-12d3-a456-426655440000")
EXECUTION = uuid.UUID("123e4567-e89b-12d3-a456-426614174000")
REFERENCE = "r" * 43


def client(handler):
    return BolnaClient(
        api_key=SecretStr("private-key"), agent_id=AGENT, transport=httpx.MockTransport(handler)
    )


def test_placement_contract_has_no_retries_or_guardrail_bypass():
    requests = []

    def handle(request):
        requests.append(request)
        assert str(request.url) == "https://api.bolna.ai/call"
        assert request.headers["Authorization"] == "Bearer private-key"
        assert json.loads(request.content) == {
            "agent_id": str(AGENT),
            "recipient_phone_number": "+15555550123",
            "user_data": {"call_ref": REFERENCE},
            "retry_config": {"enabled": False},
        }
        return httpx.Response(200, json={"execution_id": str(EXECUTION), "status": "queued"})

    provider = client(handle)
    try:
        assert provider.place_call("+15555550123", REFERENCE).execution_id == EXECUTION
        assert len(requests) == 1
    finally:
        provider.close()


@pytest.mark.parametrize(
    "status, error",
    [
        (400, CallRejectedError),
        (401, CallRejectedError),
        (403, CallRejectedError),
        (404, CallRejectedError),
        (429, CallRejectedError),
        (408, CallOutcomeUnknownError),
        (500, CallOutcomeUnknownError),
        (503, CallOutcomeUnknownError),
        (302, CallOutcomeUnknownError),
    ],
)
def test_http_failure_never_retries_or_exposes_payload(status, error):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(status, json={"message": "private-key private-phone"})

    provider = client(handle)
    try:
        with pytest.raises(error) as exc:
            provider.place_call("+15555550123", REFERENCE)
        assert "private" not in str(exc.value)
        assert len(requests) == 1
    finally:
        provider.close()


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"status": "queued", "execution_id": "invalid"},
        {"status": "completed", "execution_id": str(EXECUTION)},
    ],
)
def test_invalid_acceptance_is_unknown(body):
    provider = client(lambda _: httpx.Response(200, json=body))
    try:
        with pytest.raises(CallOutcomeUnknownError):
            provider.place_call("+15555550123", REFERENCE)
    finally:
        provider.close()


def test_timeout_never_retries():
    requests = []

    def handle(request):
        requests.append(request)
        raise httpx.ReadTimeout("private-provider-detail")

    provider = client(handle)
    try:
        with pytest.raises(CallOutcomeUnknownError):
            provider.place_call("+15555550123", REFERENCE)
        assert len(requests) == 1
    finally:
        provider.close()


@pytest.mark.parametrize(
    "phone, ref",
    [
        ("15555550123", REFERENCE),
        ("+01", REFERENCE),
        ("+15555550123", "short"),
        ("+15555550123", "x/" * 30),
    ],
)
def test_invalid_inputs_never_reach_network(phone, ref):
    def forbidden(_):
        pytest.fail("Invalid input reached HTTP")

    provider = client(forbidden)
    try:
        with pytest.raises(ValueError):
            provider.place_call(phone, ref)
    finally:
        provider.close()


@pytest.mark.parametrize("change", [None, "agent", "execution", "status", "http", "json"])
def test_execution_scoped_and_sensitive_fields_discarded(change):
    def handle(request):
        assert request.method == "GET"
        assert str(request.url) == "https://api.bolna.ai/executions/" + str(EXECUTION)
        body = {
            "id": str(EXECUTION),
            "agent_id": str(AGENT),
            "status": "completed",
            "transcript": "private-transcript",
            "telephony_data": {"to_number": "private-phone"},
        }
        if change in {"agent", "execution"}:
            body["agent_id" if change == "agent" else "id"] = str(uuid.uuid4())
        elif change == "status":
            body["status"] = "invented"
        elif change == "http":
            return httpx.Response(403, json=body)
        elif change == "json":
            return httpx.Response(200, text="private-invalid-json")
        return httpx.Response(200, json=body)

    provider = client(handle)
    try:
        if change:
            with pytest.raises(VoiceProviderUnavailableError) as exc:
                provider.execution(EXECUTION)
            assert "private" not in str(exc.value)
        else:
            result = provider.execution(EXECUTION)
            assert result.status == "completed" and result.agent_id == AGENT
            assert "private" not in repr(result)
    finally:
        provider.close()


def test_settings_optional_and_client_construction_does_not_call_provider(settings):
    assert settings.bolna_api_key is None and settings.bolna_agent_id is None
    with pytest.raises(ValueError):
        BolnaClient.from_settings(settings)
    configured = Settings(
        _env_file=None,
        database_url=settings.database_url,
        bolna_api_key="private-key",
        bolna_agent_id=str(AGENT),
    )
    assert "private-key" not in repr(configured)
    provider = BolnaClient.from_settings(configured)
    provider.close()
    assert (
        Settings(
            _env_file=None, database_url=settings.database_url, bolna_api_key="", bolna_agent_id=""
        ).bolna_agent_id
        is None
    )
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=settings.database_url, bolna_agent_id="not-a-uuid")


@pytest.mark.parametrize(
    "change",
    [None, "wallet", "capacity", "processing", "task", "agent", "http", "json", "schema"],
)
def test_readiness_get_only_and_scoped(change):
    requests = []

    def handle(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.headers["Authorization"] == "Bearer private-key"
        if request.url.path == "/user/me":
            body = {
                "wallet": 0 if change == "wallet" else 5,
                "concurrency": {"max": 10, "current": 10 if change == "capacity" else 0},
                "email": "private-email",
            }
            if change == "http":
                return httpx.Response(401, json={"error": "private-key"})
            if change == "json":
                return httpx.Response(200, text="private-invalid-json")
            if change == "schema":
                body["wallet"] = "private-invalid-wallet"
            return httpx.Response(200, json=body)
        assert request.url.path == "/v2/agent/" + str(AGENT)
        return httpx.Response(
            200,
            json={
                "id": str(uuid.uuid4() if change == "agent" else AGENT),
                "agent_status": "processing" if change == "processing" else "processed",
                "tasks": [] if change == "task" else [{"task_type": "conversation"}],
                "agent_prompts": {"private": "private-prompt"},
            },
        )

    provider = client(handle)
    try:
        if change in {"agent", "http", "json", "schema"}:
            with pytest.raises(VoiceProviderUnavailableError) as exc:
                provider.readiness()
            assert "private" not in str(exc.value)
        else:
            result = provider.readiness()
            assert result.ready is (change is None)
            assert not result.turn_delivery_verified
            assert "private" not in repr(result)
        assert len(requests) == (1 if change in {"http", "json", "schema"} else 2)
    finally:
        provider.close()


def test_readiness_timeout_has_no_retry():
    requests = []

    def handle(request):
        requests.append(request)
        raise httpx.ReadTimeout("private-detail")

    provider = client(handle)
    try:
        with pytest.raises(
            VoiceProviderUnavailableError, match="^Bolna readiness could not be verified$"
        ):
            provider.readiness()
        assert len(requests) == 1
    finally:
        provider.close()
