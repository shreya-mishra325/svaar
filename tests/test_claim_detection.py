"""Claim detection suggests record_claim only; it never records or judges a claim."""

from datetime import timedelta

import pytest
from factories import make_org, make_principal
from sqlalchemy import func, select
from test_agent_loop import FakeEngine, FakeModel

from svaar.actions.catalog import build_registry
from svaar.actions.dispatcher import ApprovalPolicy, Dispatcher
from svaar.actions.registry import Channel, ToolContext
from svaar.agent.llm import ModelReply
from svaar.agent.loop import CLAIM_HINT, AgentLoop
from svaar.decisions.models import DecisionRecord
from svaar.decisions.service import DecisionService
from svaar.incidents.models import Claim

pytestmark = pytest.mark.postgres


def turn(session, text, engine):
    org = make_org(session)
    person = make_principal(session, org)
    model = FakeModel(ModelReply("Noted."))
    loop = AgentLoop(
        model,
        Dispatcher(build_registry(), ApprovalPolicy(timedelta(minutes=10), 3, False)),
        DecisionService(engine, high=0.85, low=0.55),
    )
    try:
        context = ToolContext(org.id, person.id, Channel.CHAT, None, "chat-1")
        assert loop.run(session, context, text).reply == "Noted."
    finally:
        loop.close()
    return model.requests[0]["messages"][0]["content"]


def detections(session):
    return session.scalars(
        select(DecisionRecord).where(DecisionRecord.question == "claim_detection")
    ).all()


def test_confident_detection_suggests_recording_and_is_audited(db_session):
    engine = FakeEngine(intent="claim")
    system = turn(db_session, "The fix is merged.", engine)
    assert CLAIM_HINT in system
    assert engine.calls == [("claim_detection",)]
    [record] = detections(db_session)
    assert (record.answer, record.policy_outcome) == ("claim", "act")
    assert record.action_taken == "suggested_record_claim"
    assert db_session.scalar(select(func.count()).select_from(Claim)) == 0


@pytest.mark.parametrize(
    ("text", "engine"),
    [
        ("The fix is merged.", FakeEngine(intent="no_claim")),
        ("The fix is merged.", FakeEngine(intent="claim", confidence=0.6)),
        ("What happened in the last incident?", FakeEngine(intent="claim")),
    ],
)
def test_uncertain_or_unrelated_messages_add_no_hint(db_session, text, engine):
    assert CLAIM_HINT not in turn(db_session, text, engine)
    if "merged" not in text:
        assert engine.calls == [] and detections(db_session) == []


def test_without_a_classifier_nothing_is_asked(db_session):
    assert CLAIM_HINT not in turn(db_session, "The build passed.", None)
    assert detections(db_session) == []
