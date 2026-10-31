"""Guarded local escalation preparation; no provider clients or live dialing."""

import hashlib
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from svaar.decisions.policy import PolicyOutcome
from svaar.decisions.questions import CI_FAILURE_CATEGORY, ESCALATION_STEP
from svaar.decisions.service import DecisionService
from svaar.identity.service import get_principal
from svaar.incidents.models import Incident
from svaar.jobs.models import EscalationJob

logger = logging.getLogger(__name__)
AlertTime = Callable[[Session, uuid.UUID, uuid.UUID, uuid.UUID], datetime | None]
PrepareCall = Callable[[Session, uuid.UUID, uuid.UUID, uuid.UUID], uuid.UUID | None]
Nudge = Callable[[Session, uuid.UUID, uuid.UUID, uuid.UUID, bool], bool]


class EscalationWorker:
    """Bounded row-claimed jobs; failed preparation rolls back independently."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        delivered_alert_at: AlertTime,
        prepare_call: PrepareCall,
        after_seconds: int = 600,
        cooldown_seconds: int = 3600,
        batch_size: int = 10,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        decisions: DecisionService | None = None,
        nudge: Nudge | None = None,
    ) -> None:
        if (
            not 60 <= after_seconds <= 86400
            or not 60 <= cooldown_seconds <= 86400
            or not 1 <= batch_size <= 50
        ):
            raise ValueError("Invalid escalation preparation limits")
        self.sessions, self.alert_time, self.prepare_call = (
            sessions,
            delivered_alert_at,
            prepare_call,
        )
        self.after = timedelta(seconds=after_seconds)
        self.cooldown = timedelta(seconds=cooldown_seconds)
        self.batch_size, self.now = batch_size, now
        self.decisions, self.nudge = decisions, nudge

    def _seed(self, now: datetime) -> None:
        """Create bounded durable work without claiming it or mutating incident facts."""
        with self.sessions.begin() as session:
            incidents = session.scalars(
                select(Incident)
                .where(
                    Incident.state == "open",
                    Incident.owner_principal_id.is_not(None),
                    ~exists(
                        select(EscalationJob.id).where(EscalationJob.incident_id == Incident.id)
                    ),
                )
                .order_by(Incident.created_at, Incident.id)
                .limit(self.batch_size)
            ).all()
            for incident in incidents:
                session.execute(
                    insert(EscalationJob)
                    .values(
                        id=uuid.uuid4(),
                        org_id=incident.org_id,
                        incident_id=incident.id,
                        principal_id=incident.owner_principal_id,
                        state="waiting",
                        next_check_at=now,
                    )
                    .on_conflict_do_nothing(index_elements=["incident_id"])
                )

    @staticmethod
    def _defer(job: EscalationJob, reason: str, when: datetime) -> None:
        job.state, job.reason, job.next_check_at = "deferred", reason, when

    def _prepare(self, session: Session, job: EscalationJob, now: datetime) -> str:
        incident = session.scalar(
            select(Incident)
            .where(
                Incident.id == job.incident_id,
                Incident.org_id == job.org_id,
            )
            .with_for_update()
        )
        if (
            incident is None
            or incident.state != "open"
            or incident.owner_principal_id != job.principal_id
            or get_principal(session, job.org_id, job.principal_id) is None
        ):
            job.state, job.reason = "canceled", "incident_or_owner_changed"
            return "canceled"
        sent_at = self.alert_time(session, job.org_id, job.principal_id, incident.id)
        if sent_at is None:
            self._defer(job, "alert_not_delivered", now + timedelta(seconds=60))
            return "deferred"
        if sent_at.tzinfo is None or sent_at > now:
            self._defer(job, "invalid_alert_time", now + timedelta(seconds=60))
            return "deferred"
        if sent_at + self.after > now:
            self._defer(job, "acknowledgement_grace", sent_at + self.after)
            return "deferred"
        if self.decisions is not None and job.advised_at is None:
            if self._advise(session, job, incident, sent_at, now):
                return "deferred"

        lock = int.from_bytes(
            hashlib.sha256(
                f"escalation-recipient:{job.org_id}:{job.principal_id}".encode(),
            ).digest()[:8],
            "big",
            signed=True,
        )
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
        latest = session.scalar(
            select(EscalationJob.prepared_at)
            .where(
                EscalationJob.org_id == job.org_id,
                EscalationJob.principal_id == job.principal_id,
                EscalationJob.state == "prepared",
                EscalationJob.prepared_at > now - self.cooldown,
            )
            .order_by(EscalationJob.prepared_at.desc())
            .limit(1)
        )
        if latest is not None:
            self._defer(job, "recipient_cooldown", latest + self.cooldown)
            return "deferred"
        call_id = self.prepare_call(session, job.org_id, job.principal_id, incident.id)
        if call_id is None:
            self._defer(job, "verified_phone_unavailable", now + timedelta(seconds=60))
            return "deferred"
        job.state, job.call_id, job.prepared_at, job.reason = "prepared", call_id, now, None
        return "prepared"

    def _advise(
        self,
        session: Session,
        job: EscalationJob,
        incident: Incident,
        sent_at: datetime,
        now: datetime,
    ) -> bool:
        """Ask both alert-time slots once; advice may delay one grace period, never hasten."""
        minutes = int((now - sent_at).total_seconds() // 60)
        state = (
            f"CI workflow {incident.workflow_name or 'unknown'} failed "
            f"{incident.failure_count} time(s) on branch {incident.head_branch or 'unknown'}. "
            f"The owner alert was delivered {minutes} minutes ago and is unacknowledged."
        )
        category, step = self.decisions.decide(
            session,
            org_id=job.org_id,
            state=state,
            questions=[CI_FAILURE_CATEGORY, ESCALATION_STEP],
            incident_id=incident.id,
        )
        job.advised_at = now
        flaky = category.outcome is PolicyOutcome.ACT and category.decision.value == "flaky"
        advice = step.decision.value if step.outcome is PolicyOutcome.ACT else "call_now"
        if flaky:
            action = "quiet_note_and_wait"
        elif advice == "chat_nudge":
            action = "chat_nudge_and_wait"
        elif advice == "wait":
            action = "wait"
        else:
            action = "escalation_continued"
        for result in (category, step):
            if result.record is not None:
                result.record.action_taken = action
        if action == "escalation_continued":
            return False
        if action != "wait" and self.nudge is not None:
            self.nudge(session, job.org_id, job.principal_id, incident.id, flaky)
        self._defer(job, "advised_" + ("flaky" if flaky else advice), now + self.after)
        return True

    def run_once(self) -> dict[str, int]:
        """Prepare local intents only; no failures in one job escape to another."""
        now = self.now()
        if now.tzinfo is None:
            raise ValueError("Use a timezone-aware escalation clock")
        counts = dict(prepared=0, deferred=0, canceled=0, failed=0)
        self._seed(now)
        for _ in range(self.batch_size):
            with self.sessions.begin() as session:
                job = session.scalar(
                    select(EscalationJob)
                    .where(
                        EscalationJob.state.in_(("waiting", "deferred")),
                        EscalationJob.next_check_at <= now,
                    )
                    .order_by(EscalationJob.next_check_at, EscalationJob.id)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                if job is None:
                    break
                try:
                    with session.begin_nested():
                        outcome = self._prepare(session, job, now)
                        session.flush()
                except Exception as exc:
                    self._defer(job, "preparation_error", now + timedelta(seconds=60))
                    logger.error(
                        "escalation_preparation_failed", extra={"error_type": type(exc).__name__}
                    )
                    outcome = "failed"
                counts[outcome] += 1
        return counts
