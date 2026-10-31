"""Alert-time advice is audited per slot and can only delay escalation once."""

from collections.abc import Sequence
from datetime import timedelta

import pytest
from sqlalchemy import select
from test_escalation_jobs import NOW, calls, escalation_scope

from svaar.agent.models import OutboxMessage
from svaar.agent.notifications import delivered_incident_alert_at, enqueue_escalation_nudge
from svaar.decisions.models import DecisionRecord
from svaar.decisions.policy import is_valid
from svaar.decisions.questions import CI_FAILURE_CATEGORY, ESCALATION_STEP, Question
from svaar.decisions.service import DecisionService
from svaar.decisions.types import Decision
from svaar.jobs.escalation import EscalationWorker
from svaar.jobs.models import EscalationJob
from svaar.voice.calls import prepare_escalation_call

pytestmark = pytest.mark.postgres


@pytest.fixture
def scope(session_factory):
    return escalation_scope(session_factory)


class Advice:
    def __init__(self, category="test", step="call_now", confidence=0.95) -> None:
        self.labels = {"ci_failure_category": category, "escalation_step": step}
        self.confidence = confidence
        self.calls: list[tuple[str, ...]] = []

    def decide(self, state: str, questions: Sequence[Question]) -> list[Decision]:
        self.calls.append(tuple(q.name for q in questions))
        assert "Deploy" in state and "+1" not in state
        return [
            Decision(q.name, self.labels[q.name], self.confidence, model_version="test")
            for q in questions
        ]


def advised(sessions, engine, at=NOW):
    return EscalationWorker(
        sessions,
        delivered_alert_at=delivered_incident_alert_at,
        prepare_call=prepare_escalation_call,
        now=lambda: at,
        decisions=DecisionService(engine, high=0.85, low=0.55),
        nudge=enqueue_escalation_nudge,
    )


def nudges(sessions):
    with sessions() as session:
        return session.scalars(
            select(OutboxMessage.body).where(
                OutboxMessage.notification_key.like("escalation-nudge:%")
            )
        ).all()


def audit(sessions):
    with sessions() as session:
        rows = session.scalars(select(DecisionRecord).order_by(DecisionRecord.question)).all()
        return [(row.question, row.answer, row.action_taken) for row in rows]


@pytest.mark.parametrize(
    ("category", "step", "action", "nudged"),
    [
        ("flaky", "call_now", "quiet_note_and_wait", "flaky"),
        ("test", "chat_nudge", "chat_nudge_and_wait", "Reminder"),
        ("test", "wait", "wait", None),
    ],
)
def test_confident_advice_delays_exactly_once(
    session_factory, scope, category, step, action, nudged
):
    engine = Advice(category, step)
    assert advised(session_factory, engine).run_once()["deferred"] == 1
    assert calls(session_factory) == []
    assert engine.calls == [("ci_failure_category", "escalation_step")]
    assert [row[2] for row in audit(session_factory)] == [action, action]
    bodies = nudges(session_factory)
    assert (bodies and nudged in bodies[0]) if nudged else bodies == []
    later = NOW + timedelta(seconds=601)
    assert advised(session_factory, engine, later).run_once()["prepared"] == 1
    assert len(engine.calls) == 1 and len(calls(session_factory)) == 1


@pytest.mark.parametrize(
    "engine", [Advice("test", "call_now"), Advice("flaky", "wait", confidence=0.6)]
)
def test_unconfident_or_call_now_advice_keeps_deterministic_timing(session_factory, scope, engine):
    assert advised(session_factory, engine).run_once()["prepared"] == 1
    assert nudges(session_factory) == []
    assert {row[2] for row in audit(session_factory)} == {"escalation_continued"}


def test_no_advice_before_grace(session_factory, scope):
    engine = Advice("flaky", "wait")
    early = NOW - timedelta(seconds=300)
    assert advised(session_factory, engine, early).run_once()["deferred"] == 1
    assert engine.calls == [] and audit(session_factory) == []


def test_heuristic_fallback_never_delays_escalation(session_factory, scope):
    assert advised(session_factory, None).run_once()["prepared"] == 1
    assert {row[2] for row in audit(session_factory)} == {"escalation_continued"}
    with session_factory() as session:
        assert set(session.scalars(select(DecisionRecord.source))) == {"fallback"}
        assert session.scalar(select(EscalationJob.advised_at)) is not None


@pytest.mark.parametrize(
    ("question", "label"),
    [(q, label) for q in (CI_FAILURE_CATEGORY, ESCALATION_STEP) for label in q.labels],
)
def test_every_allowed_label_validates(question, label):
    assert is_valid(Decision(question.name, label, 0.9), question)
    assert not is_valid(Decision(question.name, label + "_invented", 0.9), question)


def test_malformed_category_keeps_the_valid_escalation_answer(session_factory, scope):
    engine = Advice("not_a_category", "wait")
    assert advised(session_factory, engine).run_once()["deferred"] == 1
    assert engine.calls == [("ci_failure_category", "escalation_step")]
    with session_factory() as session:
        rows = {row.question: row for row in session.scalars(select(DecisionRecord))}
        category, step = rows["ci_failure_category"], rows["escalation_step"]
        assert (category.source, category.fallback_reason) == ("fallback", "invalid_answer")
        assert category.answer == "unknown"
        assert (step.source, step.answer, step.fallback_reason) == ("model", "wait", None)
        assert session.scalar(select(EscalationJob.reason)) == "advised_wait"
    assert calls(session_factory) == []
