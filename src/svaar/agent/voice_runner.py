"""Shared agent execution adapter; no imports from the voice package."""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.orm import Session

from svaar.actions.registry import ToolContext
from svaar.agent.loop import AgentLoop


class VoiceAgentExecutor:
    """Adapt the existing voice profile and decision gates to durable orchestration."""

    def __init__(self, agent: AgentLoop) -> None:
        self.agent = agent

    def __call__(
        self,
        session: Session,
        context: ToolContext,
        text: str,
        history: Sequence[Mapping[str, Any]],
    ) -> tuple[str, str]:
        """Execute via the shared loop; undeliverable secret tickets fail closed."""
        result = self.agent.run(session, context, text, history=history)
        if result.tickets:
            # Voice notification/outbox wiring is not implemented yet. Never
            # speak secret tickets or claim that a confirmation code was sent.
            raise ValueError("Voice confirmation delivery is not configured")
        return result.reply, result.reason
