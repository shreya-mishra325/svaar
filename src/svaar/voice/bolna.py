"""Bolna REST adapter, documented call/execution contracts checked 2026-10-23.

Sources: https://www.bolna.ai/docs/api-reference/calls/make
https://www.bolna.ai/docs/api-reference/executions/get_execution
https://www.bolna.ai/docs/outbound/auto-retry
No live account or turn-reference delivery is established by this adapter.
"""

import re
import uuid
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from svaar.config import Settings
from svaar.voice.provider import (
    PROGRESS_STATUSES,
    TERMINAL_STATUSES,
    CallOutcomeUnknownError,
    CallReceipt,
    CallRejectedError,
    ExecutionStatus,
    VoiceProviderUnavailableError,
)


class _Accepted(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    status: Literal["queued"]
    execution_id: uuid.UUID


class _Execution(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    id: uuid.UUID
    agent_id: uuid.UUID
    status: str = Field(min_length=1, max_length=32)


class BolnaClient:
    """A bounded synchronous client; retries, redirects and proxy inheritance disabled."""

    def __init__(
        self,
        *,
        api_key: SecretStr,
        agent_id: uuid.UUID,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key.get_secret_value().strip():
            raise ValueError("Bolna API key is required")
        self.agent_id = uuid.UUID(str(agent_id))
        self._client = httpx.Client(
            base_url="https://api.bolna.ai/",
            headers={"Authorization": "Bearer " + api_key.get_secret_value()},
            timeout=httpx.Timeout(6.0, connect=2.0),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "BolnaClient":
        """Require explicit key and agent ID; constructing a client makes no request."""
        if settings.bolna_api_key is None or settings.bolna_agent_id is None:
            raise ValueError("Configure Bolna API key and agent ID")
        return cls(api_key=settings.bolna_api_key, agent_id=settings.bolna_agent_id)

    def close(self) -> None:
        """Release the HTTP client."""
        self._client.close()

    def place_call(self, phone: str, call_ref: str) -> CallReceipt:
        """POST once, with provider auto-retries explicitly disabled.

        call_ref is a private locator sent in documented user_data. Its delivery
        to Svaar on each turn is still an unverified, separate transport contract.
        """
        if not re.fullmatch(r"\+[1-9][0-9]{7,14}", phone):
            raise ValueError("Use an E.164 recipient")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", call_ref):
            raise ValueError("A high-entropy call reference is required")
        try:
            response = self._client.post(
                "call",
                json={
                    "agent_id": str(self.agent_id),
                    "recipient_phone_number": phone,
                    "user_data": {"call_ref": call_ref},
                    "retry_config": {"enabled": False},
                },
            )
        except httpx.HTTPError:
            raise CallOutcomeUnknownError("Bolna placement outcome is unknown") from None
        if 400 <= response.status_code < 500 and response.status_code != 408:
            raise CallRejectedError("Bolna rejected call placement")
        if response.status_code != 200:
            raise CallOutcomeUnknownError("Bolna placement outcome is unknown")
        try:
            result = _Accepted.model_validate(response.json())
        except (ValueError, ValidationError):
            raise CallOutcomeUnknownError("Bolna acceptance could not be verified") from None
        return CallReceipt(result.execution_id)

    def execution(self, execution_id: uuid.UUID) -> ExecutionStatus:
        """GET one execution, checking both execution ID and configured agent."""
        identifier = uuid.UUID(str(execution_id))
        try:
            response = self._client.get("executions/" + str(identifier))
            response.raise_for_status()
            result = _Execution.model_validate(response.json())
            if (
                result.id != identifier
                or result.agent_id != self.agent_id
                or result.status not in TERMINAL_STATUSES | frozenset(PROGRESS_STATUSES)
            ):
                raise ValueError("Execution mismatch")
        except (httpx.HTTPError, ValueError, ValidationError):
            raise VoiceProviderUnavailableError("Bolna execution could not be verified") from None
        return ExecutionStatus(result.id, result.agent_id, result.status)
