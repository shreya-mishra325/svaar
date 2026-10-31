"""Shared bounded agent core; transports supply trusted identity and persistence.

This core never resolves a caller from model text and never invokes handlers
directly. Tools run synchronously in the caller's session, never in inference
workers. Callers commit audit and outbox writes and own conversation/turn dedupe.
"""

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from time import monotonic
from typing import Any

from sqlalchemy.orm import Session

from svaar.actions.dispatcher import ConfirmationTicket, Dispatcher
from svaar.actions.missions import Mission
from svaar.actions.registry import Channel, ToolContext
from svaar.agent.inference import InferencePool, TurnTimeoutError
from svaar.agent.llm import ChatModel, ModelReply, ModelUnavailableError, RetryableModelError
from svaar.agent.profiles import CHAT, VOICE, TurnProfile
from svaar.agent.prompts import system_prompt
from svaar.decisions.classifier import StructuredClassifier
from svaar.decisions.policy import PolicyOutcome
from svaar.decisions.questions import (
    CLAIM_DETECTION,
    TRANSCRIPT_USABILITY,
    VOICE_INTENT,
    Question,
)
from svaar.decisions.service import DecisionService
from svaar.decisions.types import Decision, DecisionEngine, DecisionUnavailableError
from svaar.identity.service import get_principal
from svaar.incidents.claim_checks import claim_check_brief

logger = logging.getLogger(__name__)
VOICE_FALLBACK = "I can't check that right now, I will message you."
CHAT_FALLBACK = "I couldn't finish that request. Please try again or ask an operator."
CLARIFY = "Could you repeat or clarify that request?"
HISTORY_LIMIT = 12
# Cheap local prefilter: only messages naming a work status reach the classifier.
STATUS_WORDS = re.compile(
    r"\b(merged|fixed|passed|green|deployed|shipped|done|succeeded|resolved)\b",
    re.IGNORECASE,
)
CLAIM_HINT = (
    "The caller's message may state verifiable work status. If it concerns an incident, "
    "record it with record_claim, using the exact run and attempt or the pull request "
    "number when known. Recording is not proof and does not set its status."
)


@dataclass(frozen=True)
class TurnResult:
    """Reply plus secret tickets for trusted outbox delivery, never for model history."""

    reply: str
    reason: str
    tickets: tuple[ConfirmationTicket, ...] = ()


class _BudgetedEngine:
    """Apply the turn budget to a provider engine without moving DB audit to a worker."""

    def __init__(self, engine: DecisionEngine, pool: InferencePool, deadline: float) -> None:
        self.engine, self.pool, self.deadline = engine, pool, deadline
        # Timer waits can return a few milliseconds early (notably on Windows), so a
        # deadline expiry is recorded explicitly rather than inferred from the clock.
        self.timed_out = False

    def decide(self, state: str, questions: Sequence[Question]) -> Sequence[Decision]:
        try:
            engine = self.engine
            if isinstance(engine, StructuredClassifier):
                remaining = self.deadline - monotonic()
                if remaining <= 0:
                    raise TurnTimeoutError("Decision deadline reached")
                engine = engine.with_timeout(remaining)
            return self.pool.call(lambda: engine.decide(state, questions), deadline=self.deadline)
        except TurnTimeoutError:
            self.timed_out = True
            raise DecisionUnavailableError("Decision turn deadline reached") from None


class AgentLoop:
    """One tool loop for chat and voice, injectable model and decision providers."""

    def __init__(
        self, model: ChatModel, dispatcher: Dispatcher, decisions: DecisionService
    ) -> None:
        self.model, self.dispatcher, self.decisions = model, dispatcher, decisions
        self._inference = InferencePool()

    def close(self) -> None:
        """Stop accepting inference; the composition owner separately closes its adapters."""
        self._inference.close()

    def run(
        self,
        session: Session,
        context: ToolContext,
        text: str,
        *,
        history: Sequence[Mapping[str, Any]] = (),
        profile: TurnProfile | None = None,
    ) -> TurnResult:
        """Run a trusted caller's turn, stopping before any tool exceeds turn limits.

        History must already be scoped to this caller/thread. Only user/assistant
        text is admitted; intermediate tools are ephemeral and never replayed raw.
        Callers must persist/enqueue the returned reply and any tickets atomically
        with their turn state. Do not expose tickets to the chat model or voice.
        """
        spoken = context.channel is Channel.VOICE
        profile = profile or (VOICE if spoken else CHAT)
        deadline = monotonic() + profile.deadline_seconds
        if context.deadline is not None:
            deadline = min(deadline, context.deadline)
        context = replace(context, deadline=deadline)
        fallback = VOICE_FALLBACK if spoken else CHAT_FALLBACK
        principal = get_principal(session, context.org_id, context.principal_id)
        if principal is None or (spoken and context.mission is None):
            return TurnResult("I can't access that request.", "not_authorized")
        if not spoken and context.mission is not None:
            return TurnResult("I can't access that request.", "not_authorized")

        tickets: list[ConfirmationTicket] = []
        try:
            intent = None
            if spoken:
                # Do not include the known identity in model-facing decision state.
                state = (
                    text.replace(principal.display_name, "[person]")
                    if principal.display_name
                    else text
                )
                intent = self._voice_gate(session, context, state, deadline)
                if intent is None:
                    return TurnResult(CLARIFY, "clarification_required")
            specs = self.dispatcher.available_tools(session, context)
            brief = None
            if (
                not spoken
                and any(spec.name == "record_claim" for spec in specs)
                and self._claim_detected(session, context, principal.display_name, text, deadline)
            ):
                brief = CLAIM_HINT
            if context.mission is Mission.CLAIM_CHECK and context.claim_id is not None:
                brief = claim_check_brief(
                    session, context.org_id, context.principal_id, context.claim_id
                )
            messages: list[dict[str, Any]] = [
                {
                    "role": "system",
                    "content": system_prompt(specs, spoken=spoken, intent=intent, brief=brief),
                }
            ]
            messages.extend(
                {"role": item["role"], "content": item["content"]}
                for item in list(history)[-HISTORY_LIMIT:]
                if item.get("role") in ("user", "assistant")
                and isinstance(item.get("content"), str)
            )
            messages.append({"role": "user", "content": text})
            schemas = [spec.json_schema() for spec in specs]
            for round_index in range(profile.rounds):
                reply = self._complete(messages, schemas, profile, deadline)
                self._check_deadline(deadline)
                if not reply.tools:
                    output = _spoken(reply.content) if spoken else reply.content
                    return TurnResult(output, "answered", tuple(tickets))
                # Reserve a model round to explain tool results. Never execute a
                # final-round batch and only afterwards announce a limit failure.
                if round_index == profile.rounds - 1 or len(reply.tools) > profile.calls_per_round:
                    return TurnResult(fallback, "tool_limit", tuple(tickets))
                messages.append(reply.as_message())
                for proposal in reply.tools:
                    self._check_deadline(deadline)
                    arguments = proposal.arguments
                    if proposal.name == "record_claim" and isinstance(arguments, dict):
                        # The model may select a target, but cannot invent the caller's assertion.
                        arguments = {**arguments, "statement": text}
                    if proposal.name in {"confirm_action", "verify_phone_code"}:
                        # A model's invented/transformed nonce is never confirmation.
                        arguments = {"code": text}
                    if proposal.name == "record_claim_answer":
                        # An answer is the caller's own words, never a model summary.
                        arguments = {"answer": text}
                    result = self.dispatcher.dispatch(session, context, proposal.name, arguments)
                    if result.ticket is not None:
                        tickets.append(result.ticket)
                        # No outbox receipt exists here; do not claim code delivery.
                        return TurnResult(
                            "That action is waiting for confirmation.",
                            "confirmation_required",
                            tuple(tickets),
                        )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": proposal.id,
                            "content": json.dumps(dict(result.output), default=str),
                        }
                    )
            return TurnResult(fallback, "tool_limit", tuple(tickets))
        except (TurnTimeoutError, ModelUnavailableError) as exc:
            logger.warning("agent_turn_unavailable", extra={"error_type": type(exc).__name__})
            return TurnResult(fallback, "unavailable", tuple(tickets))

    def _voice_gate(
        self, session: Session, context: ToolContext, state: str, deadline: float
    ) -> str | None:
        """Run conservative heuristics first, then at most one grouped classifier request."""
        heuristic = self.decisions.fallback.answer(state, TRANSCRIPT_USABILITY)
        if heuristic.value != "usable":
            DecisionService(None, high=self.decisions.high, low=self.decisions.low).decide(
                session,
                org_id=context.org_id,
                state=state,
                questions=[TRANSCRIPT_USABILITY],
            )
            return None
        engine = self.decisions.engine
        bounded = _BudgetedEngine(engine, self._inference, deadline) if engine is not None else None
        service = DecisionService(bounded, high=self.decisions.high, low=self.decisions.low)
        self._check_deadline(deadline)
        decisions = service.decide(
            session,
            org_id=context.org_id,
            state=state,
            questions=[TRANSCRIPT_USABILITY, VOICE_INTENT],
        )
        if bounded is not None and bounded.timed_out:
            raise TurnTimeoutError("Decision turn deadline reached")
        self._check_deadline(deadline)
        usability, intent = decisions
        if any(result.outcome is not PolicyOutcome.ACT for result in decisions):
            return None
        if usability.decision.value != "usable" or intent.decision.value == "other":
            return None
        return intent.decision.value

    def _claim_detected(
        self,
        session: Session,
        context: ToolContext,
        name: str | None,
        text: str,
        deadline: float,
    ) -> bool:
        """Ask the optional classifier once; a detection only suggests record_claim."""
        engine = self.decisions.engine
        if engine is None or STATUS_WORDS.search(text) is None:
            return False
        state = text.replace(name, "[person]") if name else text
        service = DecisionService(
            _BudgetedEngine(engine, self._inference, deadline),
            high=self.decisions.high,
            low=self.decisions.low,
        )
        [result] = service.decide(
            session, org_id=context.org_id, state=state, questions=[CLAIM_DETECTION]
        )
        detected = result.outcome is PolicyOutcome.ACT and result.decision.value == "claim"
        if result.record is not None:
            result.record.action_taken = "suggested_record_claim" if detected else None
        return detected

    def _complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[dict[str, Any]],
        profile: TurnProfile,
        deadline: float,
    ) -> ModelReply:
        """Retry only safe inference failures within one absolute turn budget."""
        for attempt in range(profile.retries + 1):
            self._check_deadline(deadline)
            timeout = min(profile.http_timeout_seconds, deadline - monotonic())
            try:
                return self._inference.call(
                    lambda timeout=timeout: self.model.complete(messages, tools, timeout=timeout),
                    deadline=deadline,
                )
            except RetryableModelError:
                if attempt == profile.retries:
                    raise
            except (ModelUnavailableError, TurnTimeoutError):
                raise
            except Exception:
                raise ModelUnavailableError("Model inference failed") from None
        raise ModelUnavailableError("No model response")

    @staticmethod
    def _check_deadline(deadline: float) -> None:
        if monotonic() >= deadline:
            raise TurnTimeoutError("Turn deadline reached")


def _spoken(text: str) -> str:
    """Remove basic Markdown and bound the spoken final reply to two sentences."""
    plain = re.sub(r"[*_`#]", "", text).strip()
    return " ".join(re.split(r"(?<=[.!?])\s+", plain)[:2])[:600]
