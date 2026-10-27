"""Leased CI enrichment jobs; provider reads happen outside every DB transaction."""

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, select
from sqlalchemy.orm import Session, sessionmaker

from svaar.incidents.grouping import group_enriched_observation
from svaar.incidents.models import IncidentEvent, ObservedEvent, WorkflowLogSignature
from svaar.incidents.service import FAILURE_CONCLUSIONS
from svaar.integrations.github import queue_opened_alerts
from svaar.integrations.models import RepoMapping, WebhookDelivery
from svaar.jobs.models import CiJob

logger = logging.getLogger(__name__)
Enrich = Callable[[uuid.UUID, uuid.UUID], str]


class CiWorker:
    """Bounded polling with expiring claim tokens and independent job recovery."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        enrich: Enrich,
        *,
        batch_size: int = 5,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not 1 <= batch_size <= 20:
            raise ValueError("Invalid CI batch size")
        self.sessions, self.enrich, self.batch_size, self.now = sessions, enrich, batch_size, now

    def _claim(self) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID, bool, int] | None:
        now = self.now()
        if now.tzinfo is None:
            raise ValueError("Use a timezone-aware CI clock")
        with self.sessions.begin() as session:
            job = session.scalar(
                select(CiJob)
                .where(
                    ((CiJob.state == "pending") & (CiJob.next_check_at <= now))
                    | ((CiJob.state == "running") & (CiJob.lease_until <= now))
                )
                .order_by(CiJob.created_at, CiJob.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job is None:
                return None
            event = session.get(ObservedEvent, job.event_id)
            token = uuid.uuid4()
            job.state, job.lease_token, job.lease_until = (
                "running",
                token,
                now + timedelta(minutes=5),
            )
            job.attempts += 1
            failed = event.data.get("conclusion") in FAILURE_CONCLUSIONS
            has_signature = session.scalar(
                select(exists().where(WorkflowLogSignature.event_id == event.id))
            )
            return (
                job.id,
                token,
                job.org_id,
                job.event_id,
                failed and not has_signature,
                job.attempts,
            )

    def _finish(self, job_id: uuid.UUID, token: uuid.UUID, error: str | None) -> str:
        now = self.now()
        with self.sessions.begin() as session:
            job = session.scalar(select(CiJob).where(CiJob.id == job_id).with_for_update())
            if job is None or job.state != "running" or job.lease_token != token:
                return "superseded"
            event = session.get(ObservedEvent, job.event_id)
            mapping = session.scalar(
                select(RepoMapping)
                .where(
                    RepoMapping.repository_id == event.repository_id,
                    RepoMapping.org_id == job.org_id,
                )
                .with_for_update()
            )
            receipt = session.get(WebhookDelivery, event.source_delivery_id)
            if (
                mapping is None
                or mapping.installation_id != job.installation_id
                or event.org_id != job.org_id
                or receipt is None
                or receipt.org_id != job.org_id
                or receipt.event_id != event.id
                or receipt.state != "accepted"
                or event.source != "github"
                or not event.kind.startswith("workflow_run.")
            ):
                job.state, job.reason = "failed", "source_or_mapping_changed"
            elif (
                session.scalar(
                    select(IncidentEvent.event_id).where(IncidentEvent.event_id == event.id)
                )
                is not None
            ):
                job.state, job.reason = "done", "already_grouped"
            elif error is not None and job.attempts < 3:
                job.state, job.reason = "pending", "logs_unavailable"
                job.next_check_at = now + timedelta(seconds=60 * job.attempts)
            elif event.data.get(
                "conclusion"
            ) not in FAILURE_CONCLUSIONS and self._prior_failure_pending(session, event):
                job.state, job.reason = "pending", "earlier_failure_pending"
                job.next_check_at = now + timedelta(seconds=60)
            else:
                grouped = group_enriched_observation(
                    session,
                    event,
                    owner_principal_id=job.owner_principal_id,
                    installation_id=job.installation_id,
                )
                if grouped is not None and grouped.opened:
                    queue_opened_alerts(session, grouped.incident)
                job.state, job.reason = "done", "coarse_fallback" if error else None
            job.lease_token, job.lease_until = None, None
            return job.state

    @staticmethod
    def _prior_failure_pending(session: Session, event: ObservedEvent) -> bool:
        """Do not drop a later success while an earlier failure awaits logs."""
        return bool(
            session.scalar(
                select(
                    exists().where(
                        CiJob.event_id == ObservedEvent.id,
                        CiJob.org_id == event.org_id,
                        CiJob.state.in_(("pending", "running")),
                        ObservedEvent.repository_id == event.repository_id,
                        ObservedEvent.occurred_at <= event.occurred_at,
                        ObservedEvent.data["workflow_id"].astext
                        == str(event.data.get("workflow_id")),
                        ObservedEvent.data["head_branch"].astext == event.data.get("head_branch"),
                        ObservedEvent.data["conclusion"].astext.in_(FAILURE_CONCLUSIONS),
                    )
                )
            )
        )

    def run_once(self) -> dict[str, int]:
        """Process a bounded batch; stale workers cannot finalize another claim."""
        counts = {"done": 0, "pending": 0, "failed": 0, "superseded": 0}
        for _ in range(self.batch_size):
            claim = self._claim()
            if claim is None:
                break
            job_id, token, org_id, event_id, needs_logs, attempts = claim
            error = None
            try:
                if needs_logs:
                    if attempts > 3:
                        error = "retry_budget_exhausted"
                    else:
                        try:
                            result = self.enrich(org_id, event_id)
                            if result not in {"recorded", "duplicate"}:
                                error = "logs_not_recorded"
                        except Exception as exc:
                            logger.warning(
                                "ci_log_read_failed", extra={"error_type": type(exc).__name__}
                            )
                            error = "logs_unavailable"
                outcome = self._finish(job_id, token, error)
            except Exception as exc:
                logger.error("ci_job_failed", extra={"error_type": type(exc).__name__})
                # Grouping/alert failures roll back together. Reclaim after lease;
                # continue this batch rather than terminate unrelated jobs.
                counts["failed"] += 1
                continue
            counts[outcome] += 1
        return counts
