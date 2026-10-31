"""Risky CI tools are optional and always pass through nonce confirmation."""

import uuid
from collections.abc import Callable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from svaar.actions.registry import (
    Channel,
    ProviderOutcomeUnknownError,
    ToolCall,
    ToolContext,
    ToolSpec,
)
from svaar.identity.models import Role
from svaar.integrations.github_actions import GithubActionRejectedError


class RunActionArguments(BaseModel):
    """Exact incident, repository, installation and run attempt reviewed by the owner."""

    model_config = ConfigDict(extra="forbid")
    incident_id: uuid.UUID
    repository_id: int = Field(gt=0, le=9223372036854775807, strict=True)
    installation_id: int = Field(gt=0, le=9223372036854775807, strict=True)
    run_id: int = Field(gt=0, le=9223372036854775807, strict=True)
    run_attempt: int = Field(gt=0, le=2147483647, strict=True)


ExecuteAction = Callable[[ToolContext, str, dict], dict]


def ci_action_tools(execute: ExecuteAction) -> tuple[ToolSpec, ...]:
    """Inject a writer only at composition; no configured writer means no action tools."""

    def spec(name: str) -> ToolSpec:
        def handler(call: ToolCall) -> Mapping[str, Any]:
            result = execute(call.context, name, call.arguments.model_dump(mode="json"))
            if result.get("state") == "rejected":
                raise GithubActionRejectedError("CI action rejected")
            if result.get("state") == "unknown":
                raise ProviderOutcomeUnknownError("CI action requires reconciliation")
            return result

        return ToolSpec(
            name=name,
            description=f"Request {name} for the exact observed incident/run attempt. "
            "Always waits for owner confirmation. A receipt means accepted, never recovered. "
            "Never repeat an existing or uncertain intent; ask an operator to reconcile it.",
            arguments=RunActionArguments,
            handler=handler,
            roles=frozenset({Role.LEAD, Role.ADMIN}),
            channels=frozenset({Channel.CHAT}),
            risk_tier=2,
        )

    return tuple(spec(name) for name in ("rerun_workflow", "cancel_run"))
