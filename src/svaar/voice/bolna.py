"""Bolna REST adapter, documented call/execution contracts checked 2026-10-23.

Sources: https://www.bolna.ai/docs/api-reference/calls/make
https://www.bolna.ai/docs/api-reference/executions/get_execution
https://www.bolna.ai/docs/outbound/auto-retry
No live account or turn-reference delivery is established by this adapter.
"""

import re
import uuid
from dataclasses import dataclass
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


class _Concurrency(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    max: int = Field(strict=True, ge=0)
    current: int = Field(strict=True, ge=0)


class _Account(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    wallet: float = Field(allow_inf_nan=False)
    concurrency: _Concurrency


class _Agent(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    id: uuid.UUID
    agent_status: str
    tasks: list[dict[str, object]]


@dataclass(frozen=True)
class BolnaReadiness:
    """Sanitized GET-only account checks, never proof of working turn delivery."""

    wallet_positive: bool
    concurrency_available: bool
    agent_processed: bool
    conversation_task_present: bool
    turn_delivery_verified: bool = False

    @property
    def ready(self) -> bool:
        """Account capacity and processed agent only; no call was placed."""
        return (
            self.wallet_positive
            and self.concurrency_available
            and self.agent_processed
            and self.conversation_task_present
        )


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

    def readiness(self) -> BolnaReadiness:
        """GET /user/me and /v2/agent/{id}; discard identities and balances.

        Contracts: https://www.bolna.ai/docs/api-reference/user/info
        https://www.bolna.ai/docs/api-reference/agent/v2/get
        No call, configuration mutation or conversation delivery is attempted.
        """
        try:
            account_response = self._client.get("user/me")
            account_response.raise_for_status()
            account = _Account.model_validate(account_response.json())
            agent_response = self._client.get("v2/agent/" + str(self.agent_id))
            agent_response.raise_for_status()
            agent = _Agent.model_validate(agent_response.json())
            if agent.id != self.agent_id:
                raise ValueError("Agent mismatch")
        except (httpx.HTTPError, ValueError, ValidationError):
            raise VoiceProviderUnavailableError("Bolna readiness could not be verified") from None
        return BolnaReadiness(
            wallet_positive=account.wallet > 0,
            concurrency_available=account.concurrency.current < account.concurrency.max,
            agent_processed=agent.agent_status == "processed",
            conversation_task_present=any(
                task.get("task_type") == "conversation" for task in agent.tasks
            ),
        )

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
