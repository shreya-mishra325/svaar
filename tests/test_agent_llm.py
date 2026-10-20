"""Offline provider contract and model-output parsing tests; no live API calls."""

import json

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from svaar.agent.llm import (
    HttpChatModel,
    ModelReply,
    ModelUnavailableError,
    RetryableModelError,
    ToolRequest,
    parse_reply,
)
from svaar.agent.smoke import check_native_tools
from svaar.config import Settings


def test_http_model_contract_and_resource_cleanup() -> None:
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Ready."}}]})

    model = HttpChatModel(
        base_url="https://example.invalid/openai/v1/",
        api_key=SecretStr("example-only"),
        model="test-model",
        transport=httpx.MockTransport(respond),
    )
    try:
        reply = model.complete([{"role": "user", "content": "hello"}], [], timeout=2.5)
        assert reply.content == "Ready."
        request = requests[0]
        assert request.url.path == "/openai/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer example-only"
        assert request.extensions["timeout"]["read"] == 2.5
        body = json.loads(request.content)
        assert body == {"model": "test-model", "messages": [{"role": "user", "content": "hello"}]}
    finally:
        model.close()
    assert model._client.is_closed


@pytest.mark.parametrize(
    "status,retryable", [(401, False), (429, False), (302, False), (503, True)]
)
def test_http_errors_are_sanitized(status: int, retryable: bool) -> None:
    model = HttpChatModel(
        base_url="https://example.invalid/v1",
        api_key=SecretStr("private-token"),
        model="test",
        transport=httpx.MockTransport(lambda _: httpx.Response(status, text="private-payload")),
    )
    try:
        expected = RetryableModelError if retryable else ModelUnavailableError
        with pytest.raises(expected) as error:
            model.complete([], [], timeout=1)
        assert "private" not in str(error.value)
    finally:
        model.close()


@pytest.mark.parametrize("body", [{}, {"choices": []}, {"choices": [{"message": None}]}])
def test_bad_http_response_is_unavailable(body: object) -> None:
    model = HttpChatModel(
        base_url="https://example.invalid/v1",
        api_key=SecretStr("example"),
        model="test",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
    )
    try:
        with pytest.raises(ModelUnavailableError):
            model.complete([], [], timeout=1)
    finally:
        model.close()


def test_native_tools_take_precedence_over_json_content() -> None:
    reply = parse_reply(
        {
            "content": '{"name":"invented","arguments":{}}',
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "whoami", "arguments": "{}"},
                }
            ],
        }
    )
    assert reply.tools[0].name == "whoami"
    assert reply.tools[0].arguments == {}
    assert reply.native_tools
    assert reply.as_message()["tool_calls"][0]["id"] == "call-1"


@pytest.mark.parametrize(
    "content",
    [
        '{"name":"whoami","arguments":{}}',
        '```json\n{"tool_calls":[{"name":"whoami","arguments":{}}]}\n```',
    ],
)
def test_json_mode_tool_fallback(content: str) -> None:
    reply = parse_reply({"content": content})
    assert reply.tools[0].name == "whoami"
    assert reply.tools[0].arguments == {}
    assert not reply.native_tools


def test_json_in_prose_is_not_executed() -> None:
    assert not parse_reply({"content": 'Example: {"name":"whoami"}'}).tools


@pytest.mark.parametrize(
    "message",
    [None, {}, {"content": []}, {"content": "{invalid"}, {"content": '{"tool_calls":{}}'}],
)
def test_invalid_model_proposals_fail_closed(message: object) -> None:
    with pytest.raises(ValueError):
        parse_reply(message)


def test_malformed_arguments_are_preserved_for_dispatcher_rejection() -> None:
    reply = parse_reply(
        {"tool_calls": [{"id": "1", "function": {"name": "whoami", "arguments": "{invalid"}}]}
    )
    assert reply.tools[0].arguments == "{invalid"


def test_duplicate_native_identifiers_are_rejected() -> None:
    call = {"id": "1", "function": {"name": "whoami", "arguments": "{}"}}
    with pytest.raises(ValueError, match="Duplicate"):
        parse_reply({"tool_calls": [call, call]})


def test_http_timeout_is_retryable() -> None:
    def timeout(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private-url")

    model = HttpChatModel(
        base_url="https://example.invalid/v1",
        api_key=SecretStr("example"),
        model="test",
        transport=httpx.MockTransport(timeout),
    )
    try:
        with pytest.raises(RetryableModelError) as error:
            model.complete([], [], timeout=1)
        assert "private" not in str(error.value)
    finally:
        model.close()


@pytest.mark.parametrize(
    "fields",
    [
        {"llm_model": "test"},
        {"llm_api_key": "example"},
        {"llm_base_url": "https://example.invalid"},
        {
            "llm_base_url": "https://user:private-token@example.invalid/v1",
            "llm_api_key": "x",
            "llm_model": "x",
        },
        {
            "llm_base_url": "https://example.invalid/v1?key=private-token",
            "llm_api_key": "x",
            "llm_model": "x",
        },
        {"llm_base_url": "file:///tmp/model", "llm_api_key": "x", "llm_model": "x"},
    ],
)
def test_invalid_or_partial_model_configuration_is_rejected(fields: dict[str, str]) -> None:
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, database_url="postgresql://test:test@localhost/test", **fields)
    assert "private-token" not in str(error.value)


def test_model_configuration_is_optional_and_secret_safe() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql://test:test@localhost/test",
        llm_base_url="https://example.invalid/v1/",
        llm_api_key="private-token",
        llm_model="test",
    )
    assert settings.llm_base_url == "https://example.invalid/v1"
    assert "private-token" not in repr(settings)
    assert "private-token" not in settings.model_dump_json()


@pytest.mark.parametrize("native,correct", [(True, True), (False, True), (True, False)])
def test_smoke_probe_checks_native_shape_without_executing_tools(
    native: bool, correct: bool
) -> None:
    class ProbeModel:
        requests = 0

        def complete(self, messages, tools, *, timeout):
            expected = f"svaar-smoke-{self.requests}" if correct else "wrong"
            self.requests += 1
            return ModelReply(
                "", (ToolRequest("1", "smoke_echo", {"value": expected}),), native_tools=native
            )

    model = ProbeModel()
    if native and correct:
        result = check_native_tools(model)
        assert result["requests"] == model.requests == 3
        assert result["median_response_seconds"] >= 0
        assert result["measurement"] == "non_streaming_full_response_not_first_token"
    else:
        with pytest.raises(ModelUnavailableError):
            check_native_tools(model)
        assert model.requests == 1
