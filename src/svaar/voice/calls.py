"""Internal durable ordinary-call placement; no route, scheduler or automatic dialer."""

import hashlib
import re
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from svaar.actions.missions import Mission
from svaar.identity.models import ChannelBinding
from svaar.identity.phones import pending_phone
from svaar.identity.service import get_principal
from svaar.voice.models import VoiceCall
from svaar.voice.provider import (
    PROGRESS_STATUSES,
    TERMINAL_STATUSES,
    CallRejectedError,
    VoiceProvider,
    VoiceProviderUnavailableError,
)


class CallService:
    """Place only trusted internal intents; business callers must enforce action policy.

    This service is not wired to an API, model tool or polling job. Before live
    use it still needs account readiness, mission-specific limits and scheduling.
    It never creates an organization, principal or verified phone.
    """

    def __init__(self, sessions: sessionmaker[Session], provider: VoiceProvider) -> None:
        self.sessions, self.provider = sessions, provider

    @staticmethod
    def _phone(session: Session, call: VoiceCall) -> str | None:
        if call.mission == Mission.PHONE_VERIFY.value:
            return pending_phone(
                session,
                org_id=call.org_id,
                principal_id=call.principal_id,
                challenge_id=call.phone_challenge_id,
            )
        binding = session.get(ChannelBinding, call.phone_binding_id)
        if (
            get_principal(session, call.org_id, call.principal_id) is None
            or binding is None
            or binding.principal_id != call.principal_id
            or binding.channel != "phone"
            or binding.verified_at is None
            or not re.fullmatch(r"\+[1-9][0-9]{7,14}", binding.address)
            or call.mission == Mission.PHONE_VERIFY.value
        ):
            return None
        return binding.address

    def place(self, org_id: uuid.UUID, call_id: uuid.UUID) -> str:
        """Claim a pending intent before network I/O; never retry an uncertain placement."""
        with self.sessions() as session:
            call = session.scalar(
                select(VoiceCall)
                .where(VoiceCall.id == call_id, VoiceCall.org_id == org_id)
                .with_for_update()
            )
            if call is None:
                return "not_found"
            if call.state != "pending":
                return (
                    "reconciliation_required"
                    if call.state in {"placing", "unknown"}
                    else call.state
                )
            phone = self._phone(session, call)
            if phone is None:
                return "not_authorized"
            reference = secrets.token_urlsafe(32)
            call.call_ref_hash = hashlib.sha256(reference.encode()).hexdigest()
            call.provider_agent_id = self.provider.agent_id
            call.state = "placing"
            session.commit()  # A crash from here onwards must not repeat a POST.
            try:
                receipt = self.provider.place_call(phone, reference)
                call.execution_id = receipt.execution_id
                call.provider_status, call.state = "queued", "queued"
                session.commit()
                return "queued"
            except CallRejectedError:
                session.rollback()
                call = session.get(VoiceCall, call_id)
                call.state, call.error_code = "failed", "placement_rejected"
                session.commit()
                return "failed"
            except Exception:
                session.rollback()
                call = session.get(VoiceCall, call_id)
                call.state, call.error_code = "unknown", "placement_unknown"
                session.commit()
                return "reconciliation_required"

    def refresh(self, org_id: uuid.UUID, call_id: uuid.UUID) -> str:
        """Read receipt state; final calls never reopen and reads never redial."""
        with self.sessions() as session:
            call = session.scalar(
                select(VoiceCall)
                .where(VoiceCall.id == call_id, VoiceCall.org_id == org_id)
                .with_for_update()
            )
            if call is None:
                return "not_found"
            if call.state in {"closed", "failed"}:
                return call.state
            if call.execution_id is None or call.provider_agent_id != self.provider.agent_id:
                return "not_reconcilable"
            try:
                result = self.provider.execution(call.execution_id)
            except VoiceProviderUnavailableError:
                return "provider_unavailable"
            if (
                result.execution_id != call.execution_id
                or result.agent_id != call.provider_agent_id
            ):
                return "provider_mismatch"
            status = result.status
            if status in TERMINAL_STATUSES:
                call.state = "closed"
            elif status in PROGRESS_STATUSES:
                old = call.provider_status
                if old in PROGRESS_STATUSES and PROGRESS_STATUSES.index(
                    status
                ) < PROGRESS_STATUSES.index(old):
                    return call.state
                # Disconnected blocks new turns but is not a completed result.
                call.state = "active" if status == "in-progress" else "queued"
            else:
                return "provider_mismatch"
            call.provider_status = status
            session.commit()
            return call.state


def create_phone_verification_call(
    session: Session,
    *,
    org_id: uuid.UUID,
    principal_id: uuid.UUID,
    challenge_id: uuid.UUID,
) -> VoiceCall:
    """Create an internal pending intent; no placement occurs and caller commits."""
    if (
        pending_phone(session, org_id=org_id, principal_id=principal_id, challenge_id=challenge_id)
        is None
    ):
        raise ValueError("Phone verification challenge is unavailable")
    call = VoiceCall(
        org_id=org_id,
        principal_id=principal_id,
        mission=Mission.PHONE_VERIFY.value,
        phone_challenge_id=challenge_id,
        phone_binding_id=None,
    )
    session.add(call)
    session.flush()
    return call


def prepare_phone_verification_call(
    session: Session,
    org_id: uuid.UUID,
    principal_id: uuid.UUID,
    challenge_id: uuid.UUID,
) -> None:
    """Composition callback: prepare an intent without exposing voice models to agent."""
    create_phone_verification_call(
        session,
        org_id=org_id,
        principal_id=principal_id,
        challenge_id=challenge_id,
    )
