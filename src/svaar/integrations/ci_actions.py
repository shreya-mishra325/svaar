"""Confirmed CI mutations have a separate durable, non-retryable business intent."""

import uuid
from collections.abc import Callable
from time import monotonic
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from svaar.actions.models import ToolExecution, ToolStatus
from svaar.actions.registry import ToolContext
from svaar.approvals.models import Confirmation
from svaar.approvals.service import compute_action_hash
from svaar.config import Settings
from svaar.identity.models import Role
from svaar.identity.service import get_principal
from svaar.incidents.models import Incident, IncidentEvent, ObservedEvent
from svaar.integrations.github_actions import (
    ActionReceipt,
    GithubActionRejectedError,
    GithubActionsClient,
    GithubActionUnknownError,
)
from svaar.integrations.github_app import GithubUnavailableError
from svaar.integrations.models import CiActionIntent, RepoMapping, WebhookDelivery


class ActionProvider(Protocol):
    """Small adapter boundary; tests use fake readers and writers."""

    def execute(
        self,
        action: str,
        run_id: int,
        run_attempt: int,
        head_sha: str,
        *,
        deadline: float | None = None,
    ) -> ActionReceipt: ...
    def close(self) -> None: ...


ProviderFactory = Callable[[int, int], ActionProvider]


class CiActionService:
    """Commit intent before provider I/O and refuse repeated mutation attempts."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        provider_factory: ProviderFactory,
    ) -> None:
        self.sessions, self.provider_factory = sessions, provider_factory

    @classmethod
    def from_settings(
        cls, sessions: sessionmaker[Session], settings: Settings
    ) -> "CiActionService":
        """Construct lazily; configuration alone performs no provider request."""
        if (
            not settings.github_actions_enabled
            or settings.github_app_id is None
            or settings.github_private_key_b64 is None
        ):
            raise ValueError("Explicit write-enabled GitHub App configuration required")

        def provider(installation: int, repository: int) -> ActionProvider:
            return GithubActionsClient(
                app_id=settings.github_app_id,
                private_key_b64=settings.github_private_key_b64,
                installation_id=installation,
                repository_id=repository,
            )

        return cls(sessions, provider)

    @staticmethod
    def _authorized(
        session: Session,
        context: ToolContext,
        action: str,
        arguments: dict,
    ) -> tuple[Incident, ObservedEvent] | None:
        """Recheck exact stored confirmation, scope, current role, mapping and signed target."""
        principal = get_principal(session, context.org_id, context.principal_id)
        confirmation = session.get(Confirmation, context.confirmation_id)
        if (
            principal is None
            or principal.role not in {Role.LEAD, Role.ADMIN}
            or confirmation is None
            or confirmation.state != "confirmed"
            or confirmation.org_id != context.org_id
            or confirmation.principal_id != context.principal_id
            or confirmation.action != action
            or confirmation.arguments != arguments
            or confirmation.action_hash != compute_action_hash(action, arguments)
        ):
            return None
        started = session.scalar(
            select(ToolExecution.id).where(
                ToolExecution.confirmation_id == confirmation.id,
                ToolExecution.execution_key == str(confirmation.id),
                ToolExecution.org_id == context.org_id,
                ToolExecution.principal_id == context.principal_id,
                ToolExecution.status == ToolStatus.STARTED.value,
            )
        )
        incident = session.get(Incident, uuid.UUID(arguments["incident_id"]))
        mapping = session.get(RepoMapping, arguments["repository_id"])
        if (
            started is None
            or incident is None
            or incident.org_id != context.org_id
            or incident.repository_id != arguments["repository_id"]
            or incident.state == "resolved"
            or mapping is None
            or mapping.org_id != context.org_id
            or mapping.installation_id != arguments["installation_id"]
        ):
            return None
        event = session.scalar(
            select(ObservedEvent)
            .join(IncidentEvent, IncidentEvent.event_id == ObservedEvent.id)
            .join(WebhookDelivery, WebhookDelivery.id == ObservedEvent.source_delivery_id)
            .where(
                IncidentEvent.incident_id == incident.id,
                ObservedEvent.org_id == context.org_id,
                ObservedEvent.repository_id == arguments["repository_id"],
                ObservedEvent.source == "github",
                WebhookDelivery.state == "accepted",
                WebhookDelivery.event_id == ObservedEvent.id,
                WebhookDelivery.org_id == context.org_id,
                ObservedEvent.data["run_id"].astext == str(arguments["run_id"]),
                ObservedEvent.data["run_attempt"].astext == str(arguments["run_attempt"]),
            )
            .order_by(
                ObservedEvent.occurred_at.desc(), ObservedEvent.received_at.desc(), ObservedEvent.id
            )
            .limit(1)
        )
        if event is None:
            return None
        if action == "rerun_workflow" and event.data.get("status") != "completed":
            return None
        return incident, event

    def execute(self, context: ToolContext, action: str, arguments: dict) -> dict:
        """Own intent transactions independently of the dispatcher handler savepoint."""
        if action not in {"rerun_workflow", "cancel_run"} or context.confirmation_id is None:
            return {"accepted": False, "reason": "not_authorized"}
        if context.deadline is not None and monotonic() >= context.deadline:
            return {"accepted": False, "reason": "deadline_exceeded"}
        identifier = uuid.uuid4()
        with self.sessions.begin() as session:
            authorized = self._authorized(session, context, action, arguments)
            if authorized is None:
                return {"accepted": False, "reason": "target_or_authorization_changed"}
            _, event = authorized
            inserted = session.scalar(
                insert(CiActionIntent)
                .values(
                    id=identifier,
                    org_id=context.org_id,
                    principal_id=context.principal_id,
                    confirmation_id=context.confirmation_id,
                    action=action,
                    repository_id=arguments["repository_id"],
                    installation_id=arguments["installation_id"],
                    run_id=arguments["run_id"],
                    run_attempt=arguments["run_attempt"],
                    head_sha=event.data["head_sha"],
                    state="placing",
                )
                .on_conflict_do_nothing()
                .returning(CiActionIntent.id)
            )
            if inserted is None:
                return {"accepted": False, "reason": "existing_intent_requires_review"}
            head_sha = event.data["head_sha"]
        # No database transaction spans provider I/O. Placing is already durable.
        provider = None
        state, error, receipt = "unknown", "provider_outcome_unknown", None
        try:
            provider = self.provider_factory(
                arguments["installation_id"], arguments["repository_id"]
            )
            receipt = provider.execute(
                action,
                arguments["run_id"],
                arguments["run_attempt"],
                head_sha,
                deadline=context.deadline,
            )
            expected = 201 if action == "rerun_workflow" else 202
            if not isinstance(receipt, ActionReceipt) or receipt.status_code != expected:
                receipt = None
                raise GithubActionUnknownError("Invalid provider receipt")
            state, error = "accepted", None
        except GithubActionRejectedError:
            state, error = "rejected", "provider_rejected"
        except GithubUnavailableError:
            state, error = "rejected", "provider_preflight_failed"
        except GithubActionUnknownError:
            pass
        except Exception:
            # Unknown adapter failures are conservative; never repeat the POST.
            pass
        finally:
            if provider is not None:
                try:
                    provider.close()
                except Exception:
                    pass
        try:
            with self.sessions.begin() as session:
                intent = session.get(CiActionIntent, identifier)
                intent.state, intent.error_code = state, error
                if receipt is not None:
                    intent.status_code, intent.request_id = receipt.status_code, receipt.request_id
        except Exception:
            return {
                "accepted": False,
                "state": "unknown",
                "intent_id": str(identifier),
                "reason": "receipt_persistence_failed",
            }
        return {
            "accepted": state == "accepted",
            "state": state,
            "intent_id": str(identifier),
            "http_status": receipt.status_code if receipt else None,
            "request_id": receipt.request_id if receipt else None,
            "message": "Provider acceptance only; workflow outcome requires new observed events.",
        }
