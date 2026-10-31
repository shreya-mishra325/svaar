"""Internal durable ordinary-call placement; no route, scheduler or automatic dialer."""

import hashlib
import re
import secrets
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
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

    def __init__(
        self,
        sessions: sessionmaker[Session],
        provider: VoiceProvider,
        *,
        escalation_authorized: Callable[[Session, uuid.UUID, uuid.UUID, uuid.UUID], bool]
        | None = None,
        claim_check_authorized: Callable[[Session, uuid.UUID, uuid.UUID, uuid.UUID], bool]
        | None = None,
        daily_limit: int | None = None,
        ready: Callable[[], bool] | None = None,
    ) -> None:
        if daily_limit is not None and not 1 <= daily_limit <= 20:
            raise ValueError("Invalid per-recipient daily call limit")
        self.sessions, self.provider = sessions, provider
        self.escalation_authorized = escalation_authorized
        self.claim_check_authorized = claim_check_authorized
        self.daily_limit, self.ready = daily_limit, ready

    def _phone(self, session: Session, call: VoiceCall) -> str | None:
        if call.mission == Mission.PHONE_VERIFY.value:
            return pending_phone(
                session,
                org_id=call.org_id,
                principal_id=call.principal_id,
                challenge_id=call.phone_challenge_id,
            )
        if call.mission == Mission.ESCALATION.value and call.incident_id is not None:
            if self.escalation_authorized is None or not self.escalation_authorized(
                session,
                call.org_id,
                call.principal_id,
                call.incident_id,
            ):
                return None
        if call.mission == Mission.CLAIM_CHECK.value:
            # Without a composed guard, claim checks fail closed at dispatch time.
            if (
                call.claim_id is None
                or self.claim_check_authorized is None
                or not self.claim_check_authorized(
                    session, call.org_id, call.principal_id, call.claim_id
                )
            ):
                return None
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

    def _limit_reached(self, session: Session, call: VoiceCall) -> bool:
        """Count placements to this person in the last day under a per-recipient lock."""
        if self.daily_limit is None:
            return False
        lock = int.from_bytes(
            hashlib.sha256(f"voice-recipient:{call.org_id}:{call.principal_id}".encode()).digest()[
                :8
            ],
            "big",
            signed=True,
        )
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
        placed = session.scalar(
            select(func.count())
            .select_from(VoiceCall)
            .where(
                VoiceCall.org_id == call.org_id,
                VoiceCall.principal_id == call.principal_id,
                VoiceCall.placed_at > datetime.now(UTC) - timedelta(days=1),
            )
        )
        return placed >= self.daily_limit

    def place(self, org_id: uuid.UUID, call_id: uuid.UUID) -> str:
        """Claim a pending intent before network I/O; never retry an uncertain placement."""
        if self.ready is not None:
            try:
                ready = self.ready()
            except Exception:
                ready = False
            if not ready:
                return "provider_not_ready"
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
            if self._limit_reached(session, call):
                return "call_limit_reached"
            reference = secrets.token_urlsafe(32)
            call.call_ref_hash = hashlib.sha256(reference.encode()).hexdigest()
            call.provider_agent_id = self.provider.agent_id
            call.state, call.placed_at = "placing", datetime.now(UTC)
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
            if not apply_provider_status(call, result.status):
                return call.state
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


def apply_provider_status(call: VoiceCall, status: str) -> bool:
    """Monotonic transport lifecycle only; never establish evidence or identity."""
    if call.provider_status in TERMINAL_STATUSES:
        return False
    if status not in TERMINAL_STATUSES and status not in PROGRESS_STATUSES:
        return False
    if call.state in {"closed", "failed"}:
        if status in TERMINAL_STATUSES:
            call.provider_status = status
            return True
        return False
    if status in TERMINAL_STATUSES:
        call.state = "closed"
    else:
        old = call.provider_status
        if old in PROGRESS_STATUSES and PROGRESS_STATUSES.index(status) < PROGRESS_STATUSES.index(
            old
        ):
            return False
        call.state = "active" if status == "in-progress" else "queued"
    call.provider_status = status
    return True


def prepare_escalation_call(
    session: Session,
    org_id: uuid.UUID,
    principal_id: uuid.UUID,
    incident_id: uuid.UUID,
) -> uuid.UUID | None:
    """Prepare one local intent for exactly one verified phone; never dial here."""
    if get_principal(session, org_id, principal_id) is None:
        return None
    phones = session.scalars(
        select(ChannelBinding)
        .where(
            ChannelBinding.principal_id == principal_id,
            ChannelBinding.channel == "phone",
            ChannelBinding.verified_at.is_not(None),
        )
        .limit(2)
    ).all()
    if len(phones) != 1 or not re.fullmatch(r"\+[1-9][0-9]{7,14}", phones[0].address):
        return None
    call = VoiceCall(
        org_id=org_id,
        principal_id=principal_id,
        incident_id=incident_id,
        mission=Mission.ESCALATION.value,
        phone_binding_id=phones[0].id,
    )
    session.add(call)
    session.flush()
    return call.id


def _single_verified_phone(session: Session, principal_id: uuid.UUID) -> ChannelBinding | None:
    phones = session.scalars(
        select(ChannelBinding)
        .where(
            ChannelBinding.principal_id == principal_id,
            ChannelBinding.channel == "phone",
            ChannelBinding.verified_at.is_not(None),
        )
        .limit(2)
    ).all()
    if len(phones) != 1 or not re.fullmatch(r"\+[1-9][0-9]{7,14}", phones[0].address):
        return None
    return phones[0]


def prepare_claim_check_call(
    session: Session,
    org_id: uuid.UUID,
    principal_id: uuid.UUID,
    claim_id: uuid.UUID,
    requested_by: uuid.UUID,
) -> uuid.UUID | None:
    """Prepare one pending claim_check intent; at most one open check per claim, no dial.

    The requester is recorded only so a failed call can be reported back to them.
    """
    if (
        get_principal(session, org_id, principal_id) is None
        or get_principal(session, org_id, requested_by) is None
    ):
        return None
    phone = _single_verified_phone(session, principal_id)
    if phone is None:
        return None
    call = VoiceCall(
        org_id=org_id,
        principal_id=principal_id,
        claim_id=claim_id,
        requested_by=requested_by,
        mission=Mission.CLAIM_CHECK.value,
        phone_binding_id=phone.id,
    )
    try:
        with session.begin_nested():
            session.add(call)
            session.flush()
    except IntegrityError:
        return None  # Another check for this claim is still open.
    return call.id


def claim_check_outcome(session: Session, org_id: uuid.UUID, call_id: uuid.UUID) -> str:
    """Report completed, failed or open from receipts only; never from caller words."""
    call = session.scalar(
        select(VoiceCall).where(
            VoiceCall.id == call_id,
            VoiceCall.org_id == org_id,
            VoiceCall.mission == Mission.CLAIM_CHECK.value,
        )
    )
    if call is None or call.state == "failed":
        return "failed"
    if call.state == "closed":
        return "completed" if call.provider_status == "completed" else "failed"
    return "open"
