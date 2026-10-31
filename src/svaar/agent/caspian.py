"""Caspian hosted channel adapter, verified against its deployed OpenAPI.

References: https://api.trycaspianai.com/openapi.json and official provider source
at TryCaspian/caspian-sdk commit 718a96d6d04cb76c7ccce942d2532fd4adbfd545.
The hosted API still exposes v0.1.0 while current SDK main is a 1.0 rewrite.
We use documented HTTP via existing httpx, with no SDK dependency or provisioning.

The approved MVP policy trusts private sender addresses from the authenticated
Caspian API. These addresses may be mutable usernames, not immutable user IDs.
"""

from typing import Any, Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from svaar.agent.transport import (
    DeliveryReceipt,
    DeliveryRejectedError,
    DeliveryUncertainError,
    InboundMessage,
    PollBatch,
    TransportUnavailableError,
)
from svaar.config import Settings


class _WireModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", hide_input_in_errors=True)


class _Sender(_WireModel):
    address: str = Field(min_length=1, repr=False)


class _Message(_WireModel):
    id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    connection_id: str = Field(min_length=1)
    channel: str
    direction: str
    status: str
    sender: _Sender | None
    text: str | None = Field(repr=False)
    chat_type: str | None = None
    edited: bool = False
    auto_generated: bool = False


class _Event(_WireModel):
    id: str = Field(min_length=1)
    seq: int = Field(ge=1)
    type: str
    data: dict[str, Any] = Field(repr=False)


CaspianChannel = Literal["telegram", "slack", "discord", "email"]


class _Connection(_WireModel):
    id: str
    channel: CaspianChannel
    status: Literal["active"]
    address: str = Field(repr=False)
    capabilities: list[str]


class CaspianTransport:
    """Read one configured connection; never provision or auto-retry."""

    def __init__(
        self,
        *,
        api_key: SecretStr,
        connection_id: str,
        address: str,
        base_url: str = "https://api.trycaspianai.com",
        channel: CaspianChannel = "telegram",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if channel not in {"telegram", "slack", "discord", "email"}:
            raise ValueError("Unsupported Caspian channel")
        self.channel = channel
        if base_url.rstrip("/") != "https://api.trycaspianai.com":
            raise ValueError("Use the verified Caspian HTTPS endpoint")
        if (
            not api_key.get_secret_value().strip()
            or not connection_id.strip()
            or not address.strip()
        ):
            raise ValueError("Caspian key, connection ID and address are required")
        self.connection_id = connection_id
        self.address = address
        self._client = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            headers={"Authorization": "Bearer " + api_key.get_secret_value()},
            timeout=httpx.Timeout(5.0, connect=2.0),
            trust_env=False,
            follow_redirects=False,
            transport=transport,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "CaspianTransport":
        """Require credentials for exactly the selected channel, without connecting."""
        channel = settings.caspian_channel
        connection_id = getattr(settings, f"caspian_{channel}_connection_id")
        address = getattr(settings, f"caspian_{channel}_address")
        if not all((settings.caspian_base_url, settings.caspian_api_key, connection_id, address)):
            raise ValueError("Configure Caspian key/base URL and selected channel ID/address")
        return cls(
            api_key=settings.caspian_api_key,
            base_url=settings.caspian_base_url,
            connection_id=connection_id,
            address=address,
            channel=channel,
        )

    def close(self) -> None:
        """Release the synchronous client."""
        self._client.close()

    def _read(self, path: str, **kwargs) -> Any:
        try:
            response = self._client.get(path, **kwargs)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            raise TransportUnavailableError("Caspian read failed") from None

    def check_connection(self) -> None:
        """Verify ownership, active state, bot address and basic capabilities."""
        body = self._read("v1/connections/" + quote(self.connection_id, safe=""))
        try:
            connection = _Connection.model_validate(body)
        except ValidationError:
            raise TransportUnavailableError("Invalid or inactive Caspian connection") from None
        if (
            connection.id != self.connection_id
            or connection.address != self.address
            or connection.channel != self.channel
            or not {"receive", "reply", "send"}.issubset(connection.capabilities)
        ):
            raise TransportUnavailableError("Caspian connection does not match configuration")

    def poll(self, *, after_seq: int, limit: int = 100) -> PollBatch:
        """Read ordered project events and accept only fresh private text.

        Other connections/types still advance the returned cursor. Malformed events
        stop the whole batch, so the caller cannot accidentally acknowledge a gap.
        The caller owns cursor persistence and message dedupe; none is in memory.
        """
        if (
            type(after_seq) is not int
            or after_seq < 0
            or type(limit) is not int
            or not 1 <= limit <= 500
        ):
            raise ValueError("Use a nonnegative cursor and a limit from 1 to 500")
        body = self._read(
            "v1/events", params={"after_seq": after_seq, "limit": limit, "order": "asc"}
        )
        if not isinstance(body, list) or len(body) > limit:
            raise TransportUnavailableError("Invalid Caspian event batch")
        messages = []
        cursor = after_seq
        try:
            for item in body:
                event = _Event.model_validate(item)
                if event.seq <= cursor:
                    raise ValueError("Unordered Caspian cursor")
                cursor = event.seq
                if event.type != "message.received":
                    continue
                connection = event.data.get("connection_id")
                if not isinstance(connection, str) or not connection:
                    raise ValueError("Missing event connection")
                if connection != self.connection_id:
                    continue
                message = _Message.model_validate(event.data.get("message"))
                if (
                    message.connection_id != self.connection_id
                    or message.channel != self.channel
                    or message.direction != "inbound"
                ):
                    raise ValueError("Mismatched channel event")
                if (
                    not self._private_message(message)
                    or message.edited
                    or message.auto_generated
                    or not message.text
                    or not message.text.strip()
                    or message.sender is None
                ):
                    continue
                messages.append(
                    InboundMessage(
                        channel=f"caspian:{self.channel}",
                        connection_id=self.connection_id,
                        external_message_id=message.id,
                        thread_id=message.conversation_id,
                        sender_address=message.sender.address,
                        text=message.text,
                        sender_authenticated=self.channel != "email",
                    )
                )
        except (ValidationError, ValueError):
            raise TransportUnavailableError("Invalid Caspian event") from None
        return PollBatch(tuple(messages), cursor)

    def _private_message(self, message: _Message) -> bool:
        """Use provider-specific privacy labels; email never grants sender trust.

        Slack channel/group DMs and Discord guilds cannot receive private codes.
        Shared Discord guild installs may therefore have no supported DM route.
        Email is diagnostic-only until authenticated sender evidence is available.
        """
        if self.channel == "email":
            return message.chat_type is None
        return (
            message.chat_type
            == {"telegram": "private", "slack": "im", "discord": "dm"}[self.channel]
        )

    def send(self, target: InboundMessage, text: str) -> DeliveryReceipt:
        """Send once; queued is acceptance only. No network send runs automatically."""
        if self.channel == "email":
            raise ValueError("Email delivery is blocked pending sender authentication")
        if (
            target.connection_id != self.connection_id
            or target.channel != f"caspian:{self.channel}"
        ):
            raise ValueError("Outbound target belongs to another connection")
        if not text.strip():
            raise ValueError("Cannot send an empty reply")
        try:
            response = self._client.post(
                "v1/messages/" + quote(target.external_message_id, safe="") + "/reply",
                json={"text": text},
            )
        except httpx.HTTPError:
            raise DeliveryUncertainError("Caspian delivery outcome is unknown") from None
        if 400 <= response.status_code < 500:
            raise DeliveryRejectedError(
                "Caspian rejected delivery", retryable=response.status_code == 429
            )
        if response.status_code != 201:
            raise DeliveryUncertainError("Caspian delivery outcome is unknown")
        return self._receipt(response, target.thread_id)

    def receipt(self, delivery_id: str, *, thread_id: str) -> DeliveryReceipt:
        """Read a persisted delivery reference instead of repeating a POST."""
        body = self._read("v1/messages/" + quote(delivery_id, safe=""))
        result = self._parse_receipt(body, thread_id)
        if result.delivery_id != delivery_id:
            raise TransportUnavailableError("Mismatched delivery reference")
        return result

    def _receipt(self, response: httpx.Response, thread_id: str) -> DeliveryReceipt:
        try:
            return self._parse_receipt(response.json(), thread_id)
        except (ValueError, TransportUnavailableError):
            raise DeliveryUncertainError("Invalid Caspian delivery receipt") from None

    def _parse_receipt(self, body: Any, thread_id: str) -> DeliveryReceipt:
        try:
            message = _Message.model_validate(body)
        except ValidationError:
            raise TransportUnavailableError("Invalid delivery receipt") from None
        if (
            message.connection_id != self.connection_id
            or message.conversation_id != thread_id
            or message.channel != self.channel
            or message.direction != "outbound"
            or message.status not in {"queued", "sent", "delivered", "failed"}
        ):
            raise TransportUnavailableError("Invalid delivery receipt")
        return DeliveryReceipt(message.id, message.status)


class CaspianTelegramTransport(CaspianTransport):
    """Backward-compatible Telegram constructor for existing callers."""

    @classmethod
    def from_settings(cls, settings: Settings) -> "CaspianTelegramTransport":
        """Select Telegram explicitly even if another gateway channel is configured."""
        return super().from_settings(settings.model_copy(update={"caspian_channel": "telegram"}))
