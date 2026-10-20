"""Decision validation, policy boundaries, fallback and per-question audit."""

from collections.abc import Sequence

import pytest
from factories import make_org
from sqlalchemy import select
from sqlalchemy.orm import Session

from svaar.decisions.fallback import HeuristicEngine
from svaar.decisions.models import DecisionRecord
from svaar.decisions.policy import PolicyOutcome, evaluate, is_valid
from svaar.decisions.questions import (
    CLAIM_ANSWER,
    P0_QUESTIONS,
    TRANSCRIPT_USABILITY,
    VOICE_INTENT,
    Question,
)
from svaar.decisions.service import DecisionService, redact
from svaar.decisions.types import Decision, DecisionSource, DecisionUnavailableError

HIGH, LOW = 0.85, 0.55


def jev(question: Question, value: str, confidence: float, **extra: object) -> Decision:
    return Decision(question.name, value, confidence, model_version="jev-test", **extra)


def test_question_definitions_are_consistent() -> None:
    for question in P0_QUESTIONS:
        assert question.fallback in question.labels
    with pytest.raises(ValueError):
        Question("bad", ("a",), {"a": "x"}, fallback="b", reversible=True)


@pytest.mark.parametrize(
    "confidence, question, expected",
    [
        (HIGH, VOICE_INTENT, PolicyOutcome.ACT),
        (HIGH - 0.01, VOICE_INTENT, PolicyOutcome.ASK),
        (LOW, VOICE_INTENT, PolicyOutcome.ASK),
        (LOW - 0.01, VOICE_INTENT, PolicyOutcome.DEFER),
        (0.99, CLAIM_ANSWER, PolicyOutcome.ASK),
    ],
)
def test_policy_boundaries(confidence: float, question: Question, expected: PolicyOutcome) -> None:
    decision = jev(question, question.labels[0], confidence)
    assert evaluate(decision, question, high=HIGH, low=LOW) is expected


def test_fallback_always_defers() -> None:
    decision = HeuristicEngine().answer("what happened to the deploy", VOICE_INTENT)
    assert decision.source is DecisionSource.FALLBACK and decision.confidence == 0.0
    assert evaluate(decision, VOICE_INTENT, high=HIGH, low=LOW) is PolicyOutcome.DEFER


@pytest.mark.parametrize(
    "decision, valid",
    [
        (jev(VOICE_INTENT, "investigate", 0.9, probabilities={"investigate": 0.9}), True),
        (jev(VOICE_INTENT, "rerun_now", 0.9), False),
        (jev(VOICE_INTENT, "other", 1.2), False),
        (jev(VOICE_INTENT, "other", float("nan")), False),
        (jev(VOICE_INTENT, "other", True), False),
        (jev(VOICE_INTENT, "other", 0.9, probabilities={"bogus": 0.1}), False),
        (jev(CLAIM_ANSWER, "confirmed", 0.9), False),
    ],
)
def test_answer_validation(decision: Decision, valid: bool) -> None:
    assert is_valid(decision, VOICE_INTENT) is valid


@pytest.mark.parametrize(
    "text, question, label",
    [
        ("", TRANSCRIPT_USABILITY, "unusable"),
        ("... ??", TRANSCRIPT_USABILITY, "unusable"),
        ("hello", TRANSCRIPT_USABILITY, "repeat"),
        ("what happened to the deploy", TRANSCRIPT_USABILITY, "usable"),
        ("my code is 4 8 1 5 1 6", VOICE_INTENT, "confirm_action"),
        ("why did the build fail", VOICE_INTENT, "explain_failure"),
        ("the fix is merged", VOICE_INTENT, "verify_claim"),
        ("show me the timeline", VOICE_INTENT, "investigate"),
        ("order a pizza", VOICE_INTENT, "other"),
        ("yes it is merged", CLAIM_ANSWER, "unsure"),
    ],
)
def test_heuristic_labels(text: str, question: Question, label: str) -> None:
    assert HeuristicEngine().answer(text, question).value == label


def test_redaction_removes_contact_details() -> None:
    redacted = redact("call +91 98765 43210 or asha@example.com about code 481516")
    assert "98765" not in redacted and "example.com" not in redacted
    assert "481516" in redacted


class FakeEngine:
    def __init__(self, answers: Sequence[Decision] | Exception) -> None:
        self.answers = answers
        self.states: list[str] = []

    def decide(self, state: str, questions: Sequence[Question]) -> Sequence[Decision]:
        self.states.append(state)
        if isinstance(self.answers, Exception):
            raise self.answers
        return self.answers


QUESTIONS = (VOICE_INTENT, TRANSCRIPT_USABILITY)
pg = pytest.mark.postgres


def run(session: Session, engine: FakeEngine | None, state: str = "what happened"):
    org = make_org(session)
    results = DecisionService(engine, high=HIGH, low=LOW).decide(
        session, org_id=org.id, state=state, questions=QUESTIONS
    )
    rows = session.scalars(select(DecisionRecord).order_by(DecisionRecord.question)).all()
    return results, {row.question: row for row in rows}


@pg
def test_valid_answers_are_audited(db_session: Session) -> None:
    engine = FakeEngine(
        [jev(VOICE_INTENT, "investigate", 0.9), jev(TRANSCRIPT_USABILITY, "usable", 0.7)]
    )
    results, rows = run(db_session, engine, "call +91 98765 43210 now")
    assert [r.outcome for r in results] == [PolicyOutcome.ACT, PolicyOutcome.ASK]
    assert "98765" not in engine.states[0]
    assert rows["voice_intent"].source == "jev" and rows["voice_intent"].fallback_reason is None
    assert rows["voice_intent"].model_version == "jev-test"
    assert len(rows["voice_intent"].state_hash) == 64


@pg
def test_invalid_answer_falls_back_alone(db_session: Session) -> None:
    engine = FakeEngine(
        [jev(VOICE_INTENT, "launch_missiles", 0.99), jev(TRANSCRIPT_USABILITY, "usable", 0.9)]
    )
    results, rows = run(db_session, engine)
    assert rows["voice_intent"].fallback_reason == "invalid_answer"
    assert rows["voice_intent"].policy_outcome == "defer"
    assert rows["transcript_usability"].source == "jev"
    assert results[1].outcome is PolicyOutcome.ACT


@pg
def test_missing_and_duplicate_answers_fall_back(db_session: Session) -> None:
    duplicate = jev(VOICE_INTENT, "investigate", 0.9)
    _, rows = run(db_session, FakeEngine([duplicate, duplicate]))
    assert {row.fallback_reason for row in rows.values()} == {"missing_answer"}


@pg
@pytest.mark.parametrize(
    "engine, reason",
    [
        (None, "engine_not_configured"),
        (FakeEngine(DecisionUnavailableError()), "engine_unavailable"),
        (FakeEngine(ValueError("malformed")), "engine_unavailable"),
    ],
)
def test_transport_failure_falls_back_for_all(
    db_session: Session, engine: FakeEngine | None, reason: str
) -> None:
    results, rows = run(db_session, engine)
    assert all(r.outcome is PolicyOutcome.DEFER for r in results)
    assert {row.fallback_reason for row in rows.values()} == {reason}
    assert {row.confidence for row in rows.values()} == {0.0}
