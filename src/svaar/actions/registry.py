"""Tool definitions and the registry that both prompts and permissions derive from."""

import uuid
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from svaar.actions.missions import Mission
from svaar.identity.models import Principal, Role

ALL_ROLES = frozenset(Role)


class Channel(StrEnum):
    """Conversation surface a tool call arrives from."""

    CHAT = "chat"
    VOICE = "voice"


@dataclass(frozen=True)
class ToolContext:
    """Server-resolved caller context; never built from model or caller assertions.

    Attributes:
        org_id: Organization of the resolved principal.
        principal_id: Principal resolved from a verified binding or a dialled call.
        channel: Surface the request arrived on.
        mission: Active call mission; required on voice, absent on chat.
        correlation_id: Identifier tying audit rows to a turn or request.
        deadline: Optional absolute monotonic deadline; provider handlers must bound
            their timeouts to its remaining budget. Never persist this clock value.
        phone_challenge_id: Server-bound pending challenge, only for phone_verify.
    """

    org_id: uuid.UUID
    principal_id: uuid.UUID
    channel: Channel
    mission: Mission | None
    correlation_id: str
    deadline: float | None = None
    phone_challenge_id: uuid.UUID | None = None


@dataclass(frozen=True)
class ToolCall:
    """Everything a handler receives once the dispatcher has authorized the call."""

    session: Session
    context: ToolContext
    principal: Principal
    arguments: BaseModel


class EmptyArguments(BaseModel):
    """Argument model for tools that take no arguments."""

    model_config = {"extra": "forbid"}


Handler = Callable[[ToolCall], Mapping[str, Any]]
TierRule = int | Callable[[ToolCall], int]


class ProviderOutcomeUnknownError(Exception):
    """Raised by a handler when a provider may have applied the effect but did not confirm."""


@dataclass(frozen=True)
class ToolSpec:
    """One registered tool.

    Attributes:
        name: Stable tool name offered to the model.
        description: Model-facing description.
        arguments: Pydantic model validating raw arguments.
        handler: Feature handler; only the dispatcher may call it.
        roles: Roles allowed to call the tool.
        channels: Surfaces the tool may be called from.
        risk_tier: 1 runs directly, 2 requires owner confirmation. A callable
            chooses the tier from validated arguments in deterministic code.
    """

    name: str
    description: str
    arguments: type[BaseModel]
    handler: Handler
    roles: frozenset[Role]
    channels: frozenset[Channel]
    risk_tier: TierRule = 1

    def tier_for(self, call: ToolCall) -> int:
        """Resolve the risk tier for validated arguments."""
        tier = self.risk_tier(call) if callable(self.risk_tier) else self.risk_tier
        if tier not in (1, 2):
            raise ValueError(f"Invalid risk tier for {self.name}")
        return tier

    def json_schema(self) -> dict[str, Any]:
        """Return an OpenAI-compatible function definition."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.arguments.model_json_schema(),
            },
        }


@dataclass
class Registry:
    """Name-indexed tool catalogue."""

    _tools: dict[str, ToolSpec] = field(default_factory=dict)

    def register(self, spec: ToolSpec) -> None:
        """Add a tool; duplicate names are a programming error."""
        if spec.name in self._tools:
            raise ValueError(f"Tool already registered: {spec.name}")
        if not spec.roles or not spec.channels:
            raise ValueError(f"Tool {spec.name} must allow at least one role and channel")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        """Return a tool by name."""
        return self._tools.get(name)

    def __iter__(self) -> Iterator[ToolSpec]:
        return iter(self._tools.values())

    def __contains__(self, name: object) -> bool:
        return name in self._tools
