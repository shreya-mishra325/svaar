"""Synthetic Caspian contracts only; no account changes or live messages."""

import json

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from svaar.agent.caspian import CaspianTelegramTransport
from svaar.agent.transport import (
    DeliveryRejectedError,
    DeliveryUncertainError,
    TransportUnavailableError,
)
from svaar.config import Settings


def message(**overrides):
    return {
        "id": "msg-1",
        "connection_id": "conn-1",
        "conversation_id": "thread-1",
        "channel": "telegram",
        "direction": "inbound",
        "status": "received",
        "sender": {"address": "mutable-username"},
        "text": "whoami",
        "chat_type": "private",
    } | overrides


def event(seq=1, *, outer="conn-1", **overrides):
    return {
        "id": "event-" + str(seq),
        "seq": seq,
        "type": "message.received",
        "data": {"connection_id": outer, "message": message(**overrides)},
    }


def adapter(handler):
    return CaspianTelegramTransport(
        api_key=SecretStr("test-only"),
        connection_id="conn-1",
        address="@test-bot",
        transport=httpx.MockTransport(handler),
    )


def test_read_contract_and_provider_address_trust():
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path == "/v1/connections/conn-1":
            return httpx.Response(
                200,
                json={
                    "id": "conn-1",
                    "channel": "telegram",
                    "status": "active",
                    "address": "@test-bot",
                    "capabilities": ["receive", "reply", "send"],
                },
            )
        return httpx.Response(200, json=[event(seq=4)])

    client = adapter(respond)
    try:
        client.check_connection()
        batch = client.poll(after_seq=3, limit=1)
        assert batch.next_cursor == 4
        inbound = batch.messages[0]
        assert inbound.external_message_id == "msg-1"
        assert inbound.channel == "caspian:telegram"
        assert inbound.sender_authenticated
        assert "mutable-username" not in repr(inbound)
        assert "whoami" not in repr(batch)
        assert requests[0].headers["authorization"] == "Bearer test-only"
        assert dict(requests[1].url.params) == {"after_seq": "3", "limit": "1", "order": "asc"}
    finally:
        client.close()
    assert client._client.is_closed


@pytest.mark.parametrize(
    "override",
    [
        {"chat_type": "group"},
        {"chat_type": None},
        {"edited": True},
        {"auto_generated": True},
        {"text": None},
        {"text": " "},
        {"sender": None},
    ],
)
def test_unsupported_messages_advance_cursor_without_becoming_commands(override):
    client = adapter(lambda _: httpx.Response(200, json=[event(**override)]))
    try:
        batch = client.poll(after_seq=0)
        assert batch.messages == () and batch.next_cursor == 1
    finally:
        client.close()


def test_other_connection_is_not_processed_but_cursor_advances():
    client = adapter(lambda _: httpx.Response(200, json=[event(outer="another")]))
    try:
        batch = client.poll(after_seq=0)
        assert not batch.messages and batch.next_cursor == 1
    finally:
        client.close()


@pytest.mark.parametrize(
    "body",
    [
        {},
        [event(seq=1), event(seq=1)],
        [event(seq=1), event(seq=0)],
        [event(connection_id="another")],
        [event(channel="email")],
        [event(sender={"address": 123})],
        [{"id": "event", "seq": True, "type": "message.received", "data": {}}],
    ],
)
def test_malformed_batch_never_returns_an_acknowledgeable_cursor(body):
    client = adapter(lambda _: httpx.Response(200, json=body))
    try:
        with pytest.raises(TransportUnavailableError):
            client.poll(after_seq=0)
    finally:
        client.close()


@pytest.mark.parametrize("status", [302, 401, 429, 503])
def test_read_errors_are_sanitized(status):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, text="private-provider-error")

    client = adapter(respond)
    try:
        with pytest.raises(TransportUnavailableError) as error:
            client.poll(after_seq=0)
        assert "private" not in str(error.value)
        assert len(requests) == 1
    finally:
        client.close()


def target(client):
    return client.poll(after_seq=0).messages[0]


def test_queued_receipt_is_not_claimed_delivered_and_can_be_queried():
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path == "/v1/events":
            return httpx.Response(200, json=[event()])
        body = message(id="out-1", direction="outbound", status="queued", sender=None)
        return httpx.Response(201 if request.method == "POST" else 200, json=body)

    client = adapter(respond)
    try:
        receipt = client.send(target(client), "reply")
        assert receipt.delivery_id == "out-1" and receipt.status == "queued"
        assert json.loads(requests[1].content) == {"text": "reply"}
        assert requests[1].url.path == "/v1/messages/msg-1/reply"
        assert client.receipt("out-1", thread_id="thread-1").status == "queued"
        assert requests[-1].method == "GET"
    finally:
        client.close()


@pytest.mark.parametrize("failure", ["timeout", "server", "malformed", "wrong_thread", "rejected"])
def test_delivery_failures_never_retry_or_expose_payload(failure):
    sends = []

    def respond(request):
        if request.method == "GET":
            return httpx.Response(200, json=[event()])
        sends.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("private", request=request)
        if failure == "server":
            return httpx.Response(503, text="private")
        if failure == "rejected":
            return httpx.Response(400, text="private")
        body = (
            {}
            if failure == "malformed"
            else message(direction="outbound", status="queued", conversation_id="other")
        )
        return httpx.Response(201, json=body)

    client = adapter(respond)
    try:
        expected = DeliveryRejectedError if failure == "rejected" else DeliveryUncertainError
        with pytest.raises(expected) as error:
            client.send(target(client), "private-reply")
        assert len(sends) == 1 and "private" not in str(error.value)
    finally:
        client.close()


def test_optional_settings_and_explicit_adapter_requirements():
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://x:x@localhost/test")
    with pytest.raises(ValueError):
        CaspianTelegramTransport.from_settings(settings)
    assert settings.caspian_api_key is None


@pytest.mark.parametrize(
    "url",
    [
        "http://api.trycaspianai.com",
        "https://attacker.invalid",
        "https://api.trycaspianai.com/?secret=x",
    ],
)
def test_credentials_cannot_be_routed_to_unverified_endpoint(url):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url="postgresql+psycopg://x:x@localhost/test",
            caspian_base_url=url,
        )


def test_probe_failure_is_sanitized(monkeypatch, capsys):
    from svaar.agent import caspian_smoke

    def unavailable():
        raise ValueError("private credential")

    monkeypatch.setattr(caspian_smoke, "Settings", unavailable)
    assert caspian_smoke.main([]) == 1
    result = capsys.readouterr().out
    assert "private" not in result and json.loads(result)["messages_sent"] == 0
