"""The single gate every tool call passes through, from chat or from a call.

Order of checks: known tool, principal in organization, channel, mission, role,
argument validation, then risk tier. Tier-2 calls create a confirmation and do
not run. Every attempt writes a ``tool_executions`` row.

Transactions: callers commit after ``dispatch``. A confirmed tier-2 execution
also commits internally, so its ``started`` record is durable before any
provider effect can happen.
"""

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from time import monotonic
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from svaar.actions.missions import mission_denial
from svaar.actions.models import ToolExecution, ToolStatus
from svaar.actions.registry import (
    ALL_ROLES,
    Channel,
    ProviderOutcomeUnknownError,
    Registry,
    ToolCall,
    ToolContext,
    ToolSpec,
)
from svaar.approvals import service as approvals
from svaar.approvals.models import Confirmation
from svaar.config import Settings
from svaar.identity.models import Principal, Role
from svaar.identity.service import get_principal

logger = logging.getLogger(__name__)

CONFIRM_ACTION = "confirm_action"


class ConfirmActionArguments(BaseModel):
    """The confirmation code exactly as typed or spoken by the caller."""

    model_config = {"extra": "forbid"}

    code: str = Field(min_length=1, max_length=64, description="The caller's exact words")


@dataclass(frozen=True)
class ApprovalPolicy:
    """Confirmation settings applied by the dispatcher."""

    ttl: timedelta
    max_attempts: int
    allow_same_channel: bool

    @classmethod
    def from_settings(cls, settings: Settings) -> "ApprovalPolicy":
        """Build the policy from validated settings."""
        return cls(
            ttl=timedelta(seconds=settings.confirmation_ttl_seconds),
            max_attempts=settings.confirmation_max_attempts,
            allow_same_channel=settings.allow_same_channel_confirmation,
        )


@dataclass(frozen=True)
class ConfirmationTicket:
    """Nonce for out-of-band delivery to the owner; never shown to the model."""

    confirmation_id: uuid.UUID
    principal_id: uuid.UUID
    action: str
    nonce: str


@dataclass(frozen=True)
class ToolResult:
    """Dispatch outcome.

    Attributes:
        status: Recorded status of this attempt.
        output: Model-facing result; contains no secrets or nonces.
        ticket: Set when a confirmation was created; deliver it through the outbox.
    """

    status: ToolStatus
    output: Mapping[str, Any] = field(default_factory=dict)
    ticket: ConfirmationTicket | None = None


class Dispatcher:
    """Authorize, validate, tier-gate, execute and audit tool calls."""

    def __init__(self, registry: Registry, policy: ApprovalPolicy) -> None:
        self.registry = registry
        self.policy = policy
        if CONFIRM_ACTION not in registry:
            registry.register(
                ToolSpec(
                    name=CONFIRM_ACTION,
                    description=(
                        "Confirm a pending action. Pass the caller's exact words containing "
                        "the confirmation code; never invent or repeat a code yourself."
                    ),
                    arguments=ConfirmActionArguments,
                    handler=_dispatcher_owned,
                    roles=ALL_ROLES,
                    channels=frozenset(Channel),
                )
            )

    def available_tools(self, session: Session, context: ToolContext) -> list[ToolSpec]:
        """Return the tools this caller may invoke here, for prompt tool policy."""
        principal = get_principal(session, context.org_id, context.principal_id)
        return [spec for spec in self.registry if _denial(spec, context, principal) is None]

    def dispatch(
        self,
        session: Session,
        context: ToolContext,
        name: str,
        raw_arguments: object,
    ) -> ToolResult:
        """Run one tool call through every check and record the attempt."""
        spec = self.registry.get(name)
        if spec is None:
            self._record(session, context, name, ToolStatus.UNKNOWN_TOOL)
            return ToolResult(ToolStatus.UNKNOWN_TOOL, {"error": "unknown_tool"})

        principal = get_principal(session, context.org_id, context.principal_id)
        if denial := _denial(spec, context, principal):
            self._record(session, context, name, ToolStatus.DENIED, error_code=denial)
            return ToolResult(ToolStatus.DENIED, {"error": "not_allowed", "reason": denial})
        assert principal is not None

        try:
            arguments = spec.arguments.model_validate(
                {} if raw_arguments is None else raw_arguments
            )
        except ValidationError as exc:
            self._record(session, context, name, ToolStatus.INVALID_ARGUMENTS)
            details = [
                {"location": list(error["loc"]), "type": error["type"], "message": error["msg"]}
                for error in exc.errors(include_input=False, include_url=False)
            ]
            return ToolResult(
                ToolStatus.INVALID_ARGUMENTS, {"error": "invalid_arguments", "details": details}
            )

        if spec.name == CONFIRM_ACTION:
            return self._confirm(session, context, principal, arguments)

        call = ToolCall(session=session, context=context, principal=principal, arguments=arguments)
        payload = arguments.model_dump(mode="json")
        args_hash = approvals.compute_action_hash(name, payload)
        tier = spec.tier_for(call)
        if tier == 2:
            issued = approvals.create_confirmation(
                session,
                org_id=context.org_id,
                principal_id=context.principal_id,
                action=name,
                arguments=payload,
                requested_channel=context.channel.value,
                ttl=self.policy.ttl,
            )
            self._record(
                session,
                context,
                name,
                ToolStatus.CONFIRMATION_REQUIRED,
                args_hash=args_hash,
                risk_tier=2,
                confirmation_id=issued.confirmation.id,
            )
            ticket = ConfirmationTicket(
                confirmation_id=issued.confirmation.id,
                principal_id=context.principal_id,
                action=name,
                nonce=issued.nonce,
            )
            output = {
                "status": "confirmation_required",
                "message": "Nothing has run yet. A confirmation code was sent to the owner.",
            }
            return ToolResult(ToolStatus.CONFIRMATION_REQUIRED, output, ticket)

        status, output, error_code = _run_handler(spec, call)
        self._record(
            session,
            context,
            name,
            status,
            args_hash=args_hash,
            risk_tier=1,
            error_code=error_code,
            finished=True,
        )
        return ToolResult(status, output)

    def _confirm(
        self,
        session: Session,
        context: ToolContext,
        principal: Principal,
        arguments: BaseModel,
    ) -> ToolResult:
        """Compare the code exactly, then execute the confirmed action at most once."""
        assert isinstance(arguments, ConfirmActionArguments)
        result = approvals.confirm(
            session,
            principal_id=principal.id,
            text=arguments.code,
            channel=context.channel.value,
            allow_same_channel=self.policy.allow_same_channel,
            max_attempts=self.policy.max_attempts,
        )
        if result.confirmation is None:
            self._record(
                session, context, CONFIRM_ACTION, ToolStatus.DENIED, error_code=result.outcome
            )
            return ToolResult(ToolStatus.DENIED, {"confirmed": False, "reason": result.outcome})

        self._record(
            session,
            context,
            CONFIRM_ACTION,
            ToolStatus.SUCCEEDED,
            confirmation_id=result.confirmation.id,
            finished=True,
        )
        return self._execute_confirmed(session, context, result.confirmation)

    def _execute_confirmed(
        self, session: Session, context: ToolContext, confirmation: Confirmation
    ) -> ToolResult:
        """Recheck authorization, persist ``started``, then run the handler once."""
        spec = self.registry.get(confirmation.action)
        original = ToolContext(
            org_id=confirmation.org_id,
            principal_id=confirmation.principal_id,
            channel=Channel(confirmation.requested_channel),
            mission=None,
            correlation_id=context.correlation_id,
            deadline=context.deadline,
        )
        principal = get_principal(session, confirmation.org_id, confirmation.principal_id)
        arguments: BaseModel | None = None
        if spec is None:
            denial: str | None = "unknown_tool"
        else:
            denial = _role_or_channel_denial(spec, original.channel, principal)
        if spec is not None and denial is None:
            try:
                arguments = spec.arguments.model_validate(confirmation.arguments)
            except ValidationError:
                denial = "arguments_no_longer_valid"
        if arguments is not None and denial is None:
            payload = arguments.model_dump(mode="json")
            if approvals.compute_action_hash(spec.name, payload) != confirmation.action_hash:
                denial = "action_hash_mismatch"

        execution = ToolExecution(
            org_id=confirmation.org_id,
            principal_id=confirmation.principal_id,
            tool=confirmation.action,
            args_hash=confirmation.action_hash,
            status=(ToolStatus.DENIED if denial else ToolStatus.STARTED).value,
            risk_tier=2,
            channel=original.channel.value,
            correlation_id=context.correlation_id,
            confirmation_id=confirmation.id,
            execution_key=str(confirmation.id),
            error_code=denial,
        )
        try:
            with session.begin_nested():
                session.add(execution)
        except IntegrityError:
            return ToolResult(ToolStatus.DENIED, {"confirmed": True, "reason": "already_executed"})
        session.commit()
        if denial is not None:
            logger.warning("confirmed_action_denied_at_execution", extra={"error_type": denial})
            return ToolResult(ToolStatus.DENIED, {"confirmed": True, "reason": denial})

        assert spec is not None and principal is not None and arguments is not None
        call = ToolCall(session=session, context=original, principal=principal, arguments=arguments)
        status, output, error_code = _run_handler(spec, call)
        execution.status = status.value
        execution.error_code = error_code
        execution.finished_at = func.now()
        session.commit()
        return ToolResult(
            status, {"confirmed": True, "action": spec.name, "status": status, "result": output}
        )

    def _record(
        self,
        session: Session,
        context: ToolContext,
        tool: str,
        status: ToolStatus,
        *,
        args_hash: str | None = None,
        risk_tier: int | None = None,
        confirmation_id: uuid.UUID | None = None,
        error_code: str | None = None,
        finished: bool = False,
    ) -> None:
        """Add an audit row to the caller's transaction."""
        session.add(
            ToolExecution(
                org_id=context.org_id,
                principal_id=context.principal_id,
                tool=tool,
                args_hash=args_hash,
                status=status.value,
                risk_tier=risk_tier,
                channel=context.channel.value,
                mission=context.mission.value if context.mission else None,
                correlation_id=context.correlation_id,
                confirmation_id=confirmation_id,
                error_code=error_code,
                finished_at=func.now() if finished else None,
            )
        )
        session.flush()


def _dispatcher_owned(call: ToolCall) -> Mapping[str, Any]:
    """Placeholder handler; confirm_action is executed by the dispatcher itself."""
    raise RuntimeError("confirm_action is handled by the dispatcher")


def _role_or_channel_denial(
    spec: ToolSpec, channel: Channel, principal: Principal | None
) -> str | None:
    """Check principal existence, channel and role."""
    if principal is None:
        return "unknown_principal"
    if channel not in spec.channels:
        return "channel_not_allowed"
    if Role(principal.role) not in spec.roles:
        return "role_not_allowed"
    return None


def _denial(spec: ToolSpec, context: ToolContext, principal: Principal | None) -> str | None:
    """Return the first authorization failure for this call, or None."""
    if denial := _role_or_channel_denial(spec, context.channel, principal):
        return denial
    return mission_denial(context.channel.value, context.mission, spec.name)


def _run_handler(spec: ToolSpec, call: ToolCall) -> tuple[ToolStatus, dict[str, Any], str | None]:
    """Run a handler inside a savepoint so a failure leaves no partial writes."""
    if call.context.deadline is not None and monotonic() >= call.context.deadline:
        return ToolStatus.FAILED, {"error": "deadline_exceeded"}, "deadline_exceeded"
    try:
        with call.session.begin_nested():
            output = dict(spec.handler(call))
    except ProviderOutcomeUnknownError:
        logger.error("tool_outcome_unknown", extra={"error_type": spec.name})
        return ToolStatus.OUTCOME_UNKNOWN, {"error": "outcome_unknown"}, "outcome_unknown"
    except Exception as exc:
        logger.error("tool_failed", extra={"error_type": type(exc).__name__})
        return ToolStatus.FAILED, {"error": "tool_failed"}, type(exc).__name__
    return ToolStatus.SUCCEEDED, output, None
