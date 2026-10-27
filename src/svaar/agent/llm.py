"""Synchronous OpenAI-compatible chat adapter with sanitized failure boundaries.

Contract reference: https://console.groq.com/docs/tool-use/overview
No model output executes here. The agent must dispatch every tool through actions.
"""

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from pydantic import SecretStr

from svaar.config import Settings


class ModelUnavailableError(Exception):
    """Transport, authentication, server or invalid-response failure; contains no payload."""


class RetryableModelError(ModelUnavailableError):
    """Only a timeout, transport failure or HTTP 5xx may be retried by the chat profile."""


@dataclass(frozen=True)
class ToolRequest:
    """A model proposal, not permission to execute; arguments remain untrusted."""

    id: str
    name: str
    arguments: object


@dataclass(frozen=True)
class ModelReply:
    """Parsed assistant response and normalized tool proposals."""

    content: str
    tools: tuple[ToolRequest, ...] = ()
    native_tools: bool = False

    def as_message(self) -> dict[str, Any]:
        """Return a canonical native-tool message for this turn's ephemeral history."""
        if not self.tools:
            return {"role": "assistant", "content": self.content}
        return {
            "role": "assistant",
            "content": self.content or None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                }
                for call in self.tools
            ],
        }


class ChatModel(Protocol):
    """One inference request, with retry/deadline policy owned by the agent loop."""

    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[dict[str, Any]],
        *,
        timeout: float,
    ) -> ModelReply:
        """Return a parsed response without executing any of its proposed actions."""
        ...


class HttpChatModel:
    """Small httpx adapter, injectable transport for offline contract tests."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: SecretStr,
        model: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self._client = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {api_key.get_secret_value()}"},
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "HttpChatModel":
        """Build an explicitly configured model without contacting the provider."""
        if not settings.llm_base_url or not settings.llm_api_key or not settings.llm_model:
            raise ModelUnavailableError("Chat model is not configured")
        return cls(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
        )

    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[dict[str, Any]],
        *,
        timeout: float,
    ) -> ModelReply:
        """POST chat/completions without logging prompts, credentials or response bodies."""
        payload: dict[str, Any] = {"model": self.model, "messages": list(messages)}
        if tools:
            payload.update(tools=list(tools), tool_choice="auto")
        try:
            response = self._client.post(
                "chat/completions", json=payload, timeout=httpx.Timeout(timeout)
            )
        except httpx.TransportError:
            raise RetryableModelError("Model transport failed") from None
        if response.status_code >= 500:
            raise RetryableModelError("Model server unavailable")
        if not response.is_success:
            raise ModelUnavailableError("Model request refused")
        try:
            body = response.json()
            message = body["choices"][0]["message"]
            return parse_reply(message)
        except (ValueError, TypeError, KeyError, IndexError):
            raise ModelUnavailableError("Invalid model response") from None

    def classify(self, messages: Sequence[Mapping[str, Any]], *, timeout: float) -> str:
        """Reuse one bounded chat request without tools or inference retries."""
        reply = self.complete(messages, [], timeout=timeout)
        if reply.tools:
            raise ModelUnavailableError("Classifier tool proposals are refused")
        return reply.content

    def close(self) -> None:
        """Close the pooled HTTP connections."""
        self._client.close()


def parse_reply(message: object) -> ModelReply:
    """Prefer native tool calls, then exact/fenced JSON; never extract arbitrary prose."""
    if not isinstance(message, dict):
        raise ValueError("Invalid assistant message")
    content = message.get("content") or ""
    if not isinstance(content, str):
        raise ValueError("Invalid assistant text")
    raw_calls = message.get("tool_calls")
    if raw_calls:
        if not isinstance(raw_calls, list):
            raise ValueError("Invalid native tool calls")
        calls = tuple(_native_call(call) for call in raw_calls)
    else:
        calls = _json_calls(content)
    if len({call.id for call in calls}) != len(calls):
        raise ValueError("Duplicate tool call identifiers")
    if not content.strip() and not calls:
        raise ValueError("Empty assistant reply")
    return ModelReply(content, calls, native_tools=bool(raw_calls))


def _native_call(call: object) -> ToolRequest:
    """Decode arguments where possible; malformed arguments still reach Pydantic rejection."""
    if not isinstance(call, dict) or call.get("type", "function") != "function":
        raise ValueError("Invalid tool call")
    function = call["function"]
    name, identifier = function["name"], call["id"]
    if (
        not isinstance(name, str)
        or not 1 <= len(name) <= 64
        or not isinstance(identifier, str)
        or not 1 <= len(identifier) <= 128
    ):
        raise ValueError("Invalid tool name or identifier")
    arguments = function.get("arguments", {})
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            # The dispatcher records an invalid-arguments attempt without running a handler.
            pass
    return ToolRequest(identifier, name, arguments)


def _json_calls(content: str) -> tuple[ToolRequest, ...]:
    """Accept the documented JSON-mode envelope or a single name/arguments object."""
    candidate = content.strip()
    if candidate.startswith("```") and candidate.endswith("```"):
        candidate = candidate.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    if not candidate.startswith("{"):
        return ()
    try:
        body = json.loads(candidate)
    except ValueError:
        raise ValueError("Malformed JSON-mode response") from None
    if "tool_calls" in body:
        raw_calls = body["tool_calls"]
    elif "name" in body:
        raw_calls = [body]
    else:
        return ()
    if not isinstance(raw_calls, list) or not raw_calls:
        raise ValueError("Invalid JSON-mode calls")
    result = []
    for call in raw_calls:
        if (
            not isinstance(call, dict)
            or not isinstance(call.get("name"), str)
            or not 1 <= len(call["name"]) <= 64
        ):
            raise ValueError("Invalid JSON-mode tool")
        result.append(ToolRequest(str(uuid.uuid4()), call["name"], call.get("arguments", {})))
    return tuple(result)
