"""Opt-in finalization of claim_check answers after the provider reports the call.

Rows are claimed with SKIP LOCKED and each runs in its own savepoint, so one
failure never stops another. The optional classifier request is bounded by the
classifier timeout. No provider client, dialer or claim-status model is used.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from svaar.decisions.service import DecisionService
from svaar.incidents.claim_checks import finalize_answer
from svaar.incidents.models import ClaimAnswer

logger = logging.getLogger(__name__)
CallOutcome = Callable[[Session, uuid.UUID, uuid.UUID], str]


class ClaimAnswerWorker:
    """Finalize at most ``batch_size`` recorded answers per run."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        decisions: DecisionService,
        *,
        call_outcome: CallOutcome,
        batch_size: int = 10,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not 1 <= batch_size <= 50:
            raise ValueError("Invalid claim answer batch size")
        self.sessions, self.decisions, self.call_outcome = sessions, decisions, call_outcome
        self.batch_size, self.now = batch_size, now

    def run_once(self) -> dict[str, int]:
        """Classify completed calls, discard failed ones and leave open calls waiting."""
        counts = dict(evidence=0, unverified=0, discarded=0, waiting=0, failed=0)
        seen: set[uuid.UUID] = set()
        for _ in range(self.batch_size):
            with self.sessions.begin() as session:
                query = select(ClaimAnswer).where(ClaimAnswer.state == "recorded")
                if seen:
                    query = query.where(ClaimAnswer.id.not_in(seen))
                answer = session.scalar(
                    query.order_by(ClaimAnswer.created_at, ClaimAnswer.id)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                if answer is None:
                    break
                seen.add(answer.id)
                try:
                    with session.begin_nested():
                        outcome = self.call_outcome(session, answer.org_id, answer.call_id)
                        result = finalize_answer(
                            session, self.decisions, answer, outcome, now=self.now()
                        )
                except Exception as exc:
                    logger.error(
                        "claim_answer_finalization_failed",
                        extra={"error_type": type(exc).__name__},
                    )
                    result = "failed"
                counts[result] += 1
        return counts
