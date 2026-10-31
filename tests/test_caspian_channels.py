"""Channel-specific privacy, identity and delivery contracts without live sends."""

import json
from unittest.mock import MagicMock, Mock, patch

import httpx
import pytest
from pydantic import SecretStr
from test_caspian import event, message

from svaar.agent.caspian import CaspianTransport
from svaar.agent.transport import TransportUnavailableError
from svaar.gateway import main


def adapter(channel, handler):
    return CaspianTransport(
        api_key=SecretStr("offline-only"),
        connection_id="conn-1",
        address="test-address",
        channel=channel,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize(
    "channel,privacy", [("telegram", "private"), ("slack", "im"), ("discord", "dm")]
)
def test_private_messages_use_isolated_channel_and_existing_reply_contract(channel, privacy):
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path == "/v1/events":
            return httpx.Response(200, json=[event(channel=channel, chat_type=privacy)])
        return httpx.Response(
            201 if request.method == "POST" else 200,
            json=message(
                channel=channel,
                chat_type=privacy,
                id="out-1",
                direction="outbound",
                status="queued",
            ),
        )

    with_adapter = adapter(channel, respond)
    try:
        incoming = with_adapter.poll(after_seq=0).messages[0]
        assert incoming.channel == "caspian:" + channel
        assert incoming.sender_authenticated
        receipt = with_adapter.send(incoming, "reply")
        assert receipt.status == "queued"
        assert with_adapter.receipt("out-1", thread_id="thread-1").status == "queued"
        assert requests[1].url.path == "/v1/messages/msg-1/reply"
        assert json.loads(requests[1].content) == {"text": "reply"}
    finally:
        with_adapter.close()


@pytest.mark.parametrize(
    "channel,privacy",
    [
        ("slack", "channel"),
        ("slack", "group"),
        ("slack", "mpim"),
        ("slack", None),
        ("discord", "guild"),
        ("discord", "group"),
        ("discord", None),
    ],
)
def test_group_or_unknown_privacy_never_enters_agent(channel, privacy):
    client = adapter(
        channel, lambda _: httpx.Response(200, json=[event(channel=channel, chat_type=privacy)])
    )
    try:
        batch = client.poll(after_seq=0)
        assert batch.messages == ()
        assert batch.next_cursor == 1
    finally:
        client.close()


def test_email_address_never_establishes_authenticated_identity_or_sends():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=[event(channel="email", chat_type=None)])

    client = adapter("email", respond)
    try:
        incoming = client.poll(after_seq=0).messages[0]
        assert incoming.channel == "caspian:email"
        assert not incoming.sender_authenticated
        with pytest.raises(ValueError, match="blocked"):
            client.send(incoming, "private code")
        assert all(r.method == "GET" for r in requests)
    finally:
        client.close()


@pytest.mark.parametrize("channel", ["telegram", "slack", "discord", "email"])
def test_connection_checks_channel_not_just_matching_address(channel):
    client = adapter(
        channel,
        lambda _: httpx.Response(
            200,
            json={
                "id": "conn-1",
                "channel": "email" if channel != "email" else "slack",
                "status": "active",
                "address": "test-address",
                "capabilities": ["receive", "reply", "send"],
            },
        ),
    )
    try:
        with pytest.raises(TransportUnavailableError):
            client.check_connection()
    finally:
        client.close()


@pytest.mark.parametrize("channel", ["slack", "discord", "email"])
def test_selected_settings_do_not_reuse_telegram_credentials(channel, settings):
    configured = settings.model_copy(
        update={
            "caspian_channel": channel,
            "caspian_base_url": "https://api.trycaspianai.com",
            "caspian_api_key": SecretStr("offline"),
            "caspian_telegram_connection_id": "telegram-only",
            "caspian_telegram_address": "@bot",
        }
    )
    with pytest.raises(ValueError):
        CaspianTransport.from_settings(configured)
    configured = configured.model_copy(
        update={
            f"caspian_{channel}_connection_id": "selected",
            f"caspian_{channel}_address": "address",
        }
    )
    client = CaspianTransport.from_settings(configured)
    try:
        assert client.channel == channel
        assert client.connection_id == "selected"
    finally:
        client.close()


@pytest.mark.parametrize("channel", ["slack", "discord"])
def test_gateway_routes_one_selected_channel_and_closes_resources(channel, settings):
    configured = settings.model_copy(
        update={
            "channel_transport": "caspian",
            "llm_model": "offline",
            f"caspian_{channel}_connection_id": "selected",
        }
    )
    transport, engine, model, worker = Mock(), MagicMock(), Mock(), Mock()
    with (
        patch("svaar.gateway.Settings", return_value=configured),
        patch("svaar.gateway.CaspianTransport.from_settings", return_value=transport),
        patch("svaar.gateway.create_database_engine", return_value=engine),
        patch("svaar.gateway.HttpChatModel.from_settings", return_value=model),
        patch("svaar.gateway.GatewayWorker", return_value=worker) as factory,
    ):
        assert main(["--channel", channel]) == 0
    assert factory.call_args.kwargs["channel"] == "caspian:" + channel
    assert factory.call_args.kwargs["connection_id"] == "selected"
    worker.run.assert_called_once()
    transport.close.assert_called_once()
    model.complete.assert_not_called()
    engine.dispose.assert_called_once()


def test_email_gateway_refuses_before_polling_or_sending(settings):
    configured = settings.model_copy(
        update={"channel_transport": "caspian", "llm_model": "offline"}
    )
    with (
        patch("svaar.gateway.Settings", return_value=configured),
        patch("svaar.gateway.CaspianTransport.from_settings") as transport,
        patch("svaar.gateway.create_database_engine") as database,
    ):
        assert main(["--channel", "email"]) == 2
    transport.assert_not_called()
    database.assert_not_called()
