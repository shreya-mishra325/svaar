"""claim_check calls: bound intents, exact answers and call-derived evidence.

Real PostgreSQL and action gates; fake models, classifiers and voice providers only.
"""

import uuid
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from factories import make_org, make_principal
from sqlalchemy import func, select
from test_agent_loop import FakeEngine, FakeModel, proposal
from test_incidents import deliver, incidents, run
from test_voice_calls import Provider

from svaar.actions.catalog import build_registry
from svaar.actions.dispatcher import ApprovalPolicy, Dispatcher
from svaar.actions.missions import Mission
from svaar.actions.models import ToolStatus
from svaar.actions.registry import Channel, ToolContext
from svaar.agent.llm import ModelReply
from svaar.agent.loop import AgentLoop
from svaar.agent.voice_runner import VoiceAgentExecutor
from svaar.decisions.models import DecisionRecord
from svaar.decisions.questions import Question
from svaar.decisions.service import DecisionService
from svaar.decisions.types import Decision
from svaar.identity.models import ChannelBinding, Role
from svaar.incidents.claim_checks import claim_check_authorized
from svaar.incidents.claims import ClaimInput, record_claim
from svaar.incidents.models import Claim, ClaimAnswer, ClaimEvidence, Incident
from svaar.integrations.models import RepoMapping
from svaar.jobs.claim_checks import ClaimAnswerWorker
from svaar.voice.calls import CallService, claim_check_outcome, prepare_claim_check_call
from svaar.voice.models import VoiceCall
from svaar.voice.runtime import VoiceRuntime

pytestmark = pytest.mark.postgres
NOW = datetime.now(UTC)


class AnswerEngine:
    """Fake classifier for the claim-answer slot; voice gates use FakeEngine."""

    def __init__(self, label="confirmed", confidence=0.95) -> None:
        self.label, self.confidence = label, confidence
        self.states: list[str] = []

    def decide(self, state: str, questions: Sequence[Question]) -> list[Decision]:
        self.states.append(state)
        return [
            Decision(q.name, self.label, self.confidence, model_version="classifier-test")
            for q in questions
        ]


@pytest.fixture
def scope(session_factory):
    """An incident owned by the claim author, a lead caller and a fix_merged claim."""
    with session_factory.begin() as session:
        org = make_org(session)
        author = make_principal(session, org, Role.DEV, bindings=(("phone", "+15555550123"),))
        lead = make_principal(session, org, Role.LEAD)
        session.add(
            RepoMapping(
                repository_id=101, installation_id=77, org_id=org.id, owner_principal_id=author.id
            )
        )
        ids = org.id, author.id, lead.id
    deliver(session_factory, run())
    [incident] = incidents(session_factory)
    with session_factory.begin() as session:
        claim = record_claim(
            session,
            ids[0],
            ids[1],
            ClaimInput(incident_id=incident.id, statement="The fix is merged.", kind="fix_merged"),
            "chat-message-1",
        )
        claim_id = claim.id
    return (*ids, incident.id, claim_id)


def dispatcher():
    return Dispatcher(
        build_registry(prepare_claim_call=prepare_claim_check_call),
        ApprovalPolicy(timedelta(minutes=10), 3, False),
    )


def chat(scope, principal=None):
    return ToolContext(scope[0], principal or scope[2], Channel.CHAT, None, str(uuid.uuid4()))


def verify(sessions, scope, principal=None):
    with sessions.begin() as session:
        result = dispatcher().dispatch(
            session, chat(scope, principal), "verify_claim", {"claim_id": str(scope[4])}
        )
        return result.status, dict(result.output)


def claim_calls(sessions):
    with sessions() as session:
        return list(session.scalars(select(VoiceCall).where(VoiceCall.mission == "claim_check")))


def test_owner_author_check_prepares_one_pending_intent_without_dialing(session_factory, scope):
    status, output = verify(session_factory, scope)
    assert status is ToolStatus.SUCCEEDED and output["prepared"] is True
    [call] = claim_calls(session_factory)
    assert (call.claim_id, call.principal_id, call.state) == (scope[4], scope[1], "pending")
    assert call.execution_id is None and call.call_ref_hash is None
    assert verify(session_factory, scope)[1]["reason"] == "no_verified_phone_or_check_open"
    assert len(claim_calls(session_factory)) == 1
    with session_factory() as session:
        assert session.get(Claim, scope[4]).status == "unverified"


def test_concurrent_checks_create_one_open_intent(session_factory, scope):
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: verify(session_factory, scope)[1], range(3)))
    assert sum(result.get("prepared") is True for result in results) == 1
    assert len(claim_calls(session_factory)) == 1


def test_calling_a_non_owner_author_waits_for_owner_confirmation(session_factory, scope):
    with session_factory.begin() as session:
        session.get(Incident, scope[3]).owner_principal_id = scope[2]
    status, output = verify(session_factory, scope)
    assert status is ToolStatus.CONFIRMATION_REQUIRED
    assert output["status"] == "confirmation_required"
    assert claim_calls(session_factory) == []


def test_role_phone_and_status_gates(session_factory, scope):
    status, output = verify(session_factory, scope, principal=scope[1])
    assert status is ToolStatus.DENIED and output["reason"] == "role_not_allowed"
    with session_factory.begin() as session:
        session.scalar(select(ChannelBinding)).verified_at = None
    assert verify(session_factory, scope)[1]["prepared"] is False
    assert claim_calls(session_factory) == []
    with session_factory.begin() as session:
        other = make_org(session)
        stranger = make_principal(session, other, Role.LEAD)
        foreign = ToolContext(other.id, stranger.id, Channel.CHAT, None, "foreign")
        result = dispatcher().dispatch(
            session, foreign, "verify_claim", {"claim_id": str(scope[4])}
        )
        assert result.output == {"found": False}


def test_confirmed_claim_is_never_called(session_factory, scope):
    deliver(session_factory, run(run_id=1002, conclusion="success"))
    with session_factory.begin() as session:
        claim = record_claim(
            session,
            scope[0],
            scope[1],
            ClaimInput(
                incident_id=scope[3],
                statement="The build passed.",
                kind="workflow_succeeded",
                run_id=1002,
                run_attempt=1,
            ),
            "chat-message-2",
        )
        assert claim.status == "confirmed"
        result = dispatcher().dispatch(
            session, chat(scope), "verify_claim", {"claim_id": str(claim.id)}
        )
    assert result.output["reason"] == "claim_not_unverified"
    assert claim_calls(session_factory) == []


def active_call(sessions, scope):
    assert verify(sessions, scope)[1]["prepared"] is True
    with sessions.begin() as session:
        call = session.scalar(select(VoiceCall).where(VoiceCall.mission == "claim_check"))
        call.state, call.provider_status = "active", "in-progress"
        return call.id


def voice(scope, call_id, mission=Mission.CLAIM_CHECK, claim_id=None):
    return ToolContext(
        scope[0],
        scope[1],
        Channel.VOICE,
        mission,
        "voice-turn",
        claim_id=claim_id or scope[4],
        call_id=call_id,
    )


def test_answers_are_recorded_only_inside_the_bound_call(session_factory, scope):
    call_id = active_call(session_factory, scope)
    gate = dispatcher()
    with session_factory.begin() as session:
        denied = gate.dispatch(
            session, chat(scope, scope[1]), "record_claim_answer", {"answer": "y"}
        )
        assert denied.output["reason"] == "channel_not_allowed"
        outside = gate.dispatch(
            session,
            voice(scope, call_id, Mission.ESCALATION),
            "record_claim_answer",
            {"answer": "y"},
        )
        assert outside.output["reason"] == "outside_mission"
        wrong = gate.dispatch(
            session,
            voice(scope, call_id, claim_id=uuid.uuid4()),
            "record_claim_answer",
            {"answer": "Yes."},
        )
        assert wrong.output["reason"] == "claim_unavailable"
        first = gate.dispatch(
            session, voice(scope, call_id), "record_claim_answer", {"answer": "No"}
        )
        again = gate.dispatch(
            session, voice(scope, call_id), "record_claim_answer", {"answer": "Yes, merged."}
        )
        assert first.output["recorded"] is True and again.output["recorded"] is True
    with session_factory() as session:
        [answer] = session.scalars(select(ClaimAnswer)).all()
        assert answer.answer_text == "Yes, merged." and answer.state == "recorded"
        assert session.scalar(select(func.count()).select_from(ClaimEvidence)) == 0


def test_agent_records_the_callers_words_and_briefs_the_claim(session_factory, scope):
    call_id = active_call(session_factory, scope)
    model = FakeModel(
        proposal("record_claim_answer", {"answer": "They said it is definitely merged."}),
        ModelReply("Thanks, I have noted that."),
    )
    loop = AgentLoop(
        model, dispatcher(), DecisionService(FakeEngine(intent="verify_claim"), high=0.85, low=0.55)
    )
    try:
        runtime = VoiceRuntime(session_factory, VoiceAgentExecutor(loop))
        reply = runtime.run_turn(str(call_id), "Yes, I merged it.", turn_index=0)
    finally:
        loop.close()
    assert reply == "Thanks, I have noted that."
    system = model.requests[0]["messages"][0]["content"]
    assert "'The fix is merged.'" in system and "record_claim_answer" in system
    with session_factory() as session:
        assert session.scalar(select(ClaimAnswer.answer_text)) == "Yes, I merged it."


def finish(sessions, call_id, status):
    with sessions.begin() as session:
        call = session.get(VoiceCall, call_id)
        call.state, call.provider_status = "closed", status


def record(sessions, scope, call_id, text="Yes, it was merged this morning."):
    with sessions.begin() as session:
        dispatcher().dispatch(
            session, voice(scope, call_id), "record_claim_answer", {"answer": text}
        )


def worker(sessions, engine):
    return ClaimAnswerWorker(
        sessions,
        DecisionService(engine, high=0.85, low=0.55),
        call_outcome=claim_check_outcome,
        now=lambda: NOW,
    )


@pytest.mark.parametrize(
    ("label", "confidence", "status", "stance"),
    [
        ("confirmed", 0.95, "confirmed", "supports"),
        ("denied", 0.95, "contradicted", "contradicts"),
        ("unsure", 0.95, "unverified", None),
        ("wrong_person", 0.95, "unverified", None),
        ("callback", 0.95, "unverified", None),
        ("confirmed", 0.70, "unverified", None),
        ("denied", 0.10, "unverified", None),
    ],
)
def test_completed_call_answer_maps_to_evidence_deterministically(
    session_factory, scope, label, confidence, status, stance
):
    call_id = active_call(session_factory, scope)
    record(session_factory, scope, call_id)
    finish(session_factory, call_id, "completed")
    engine = AnswerEngine(label, confidence)
    counts = worker(session_factory, engine).run_once()
    assert counts["evidence" if stance else "unverified"] == 1
    assert "The fix is merged." in engine.states[0] and "merged this morning" in engine.states[0]
    with session_factory() as session:
        assert session.get(Claim, scope[4]).status == status
        answer = session.scalar(select(ClaimAnswer))
        assert answer.answer_text is None and answer.label == label
        assert answer.finalized_at is not None
        evidence = session.scalars(select(ClaimEvidence)).all()
        assert [row.stance for row in evidence] == ([stance] if stance else [])
        if stance:
            assert evidence[0].claim_answer_id == answer.id and evidence[0].event_id is None
            assert evidence[0].rule == "claim-answer-v1"
        audit = session.get(DecisionRecord, answer.decision_id)
        assert audit.question == "claim_answer" and audit.incident_id == scope[3]
        assert audit.action_taken == (f"evidence_{stance}" if stance else "left_unverified")
    assert worker(session_factory, engine).run_once() == dict(
        evidence=0, unverified=0, discarded=0, waiting=0, failed=0
    )


def test_heuristic_fallback_never_creates_evidence(session_factory, scope):
    call_id = active_call(session_factory, scope)
    record(session_factory, scope, call_id, "Yes, confirmed, it is merged.")
    finish(session_factory, call_id, "completed")
    assert worker(session_factory, None).run_once()["unverified"] == 1
    with session_factory() as session:
        assert session.get(Claim, scope[4]).status == "unverified"
        assert session.scalar(select(func.count()).select_from(ClaimEvidence)) == 0
        assert session.scalar(select(DecisionRecord.source)) == "fallback"


@pytest.mark.parametrize("status", ["no-answer", "busy", "failed", "canceled", "error"])
def test_failed_calls_discard_answers_and_never_contradict(session_factory, scope, status):
    call_id = active_call(session_factory, scope)
    record(session_factory, scope, call_id, "No, it is not merged.")
    finish(session_factory, call_id, status)
    engine = AnswerEngine("denied", 0.99)
    assert worker(session_factory, engine).run_once()["discarded"] == 1
    assert engine.states == []
    with session_factory() as session:
        answer = session.scalar(select(ClaimAnswer))
        assert answer.state == "discarded" and answer.answer_text is None
        assert session.get(Claim, scope[4]).status == "unverified"
        assert session.scalar(select(func.count()).select_from(ClaimEvidence)) == 0


def test_open_call_answers_wait_for_completion(session_factory, scope):
    call_id = active_call(session_factory, scope)
    record(session_factory, scope, call_id)
    engine = AnswerEngine()
    assert worker(session_factory, engine).run_once()["waiting"] == 1
    assert engine.states == []
    with session_factory() as session:
        assert session.scalar(select(ClaimAnswer.state)) == "recorded"


def test_claim_checks_fail_closed_at_dispatch_without_a_current_guard(session_factory, scope):
    assert verify(session_factory, scope)[1]["prepared"] is True
    [call] = claim_calls(session_factory)
    provider = Provider()
    assert CallService(session_factory, provider).place(scope[0], call.id) == "not_authorized"
    guarded = CallService(session_factory, provider, claim_check_authorized=claim_check_authorized)
    with session_factory.begin() as session:
        session.get(Claim, scope[4]).status = "confirmed"
    assert guarded.place(scope[0], call.id) == "not_authorized"
    with session_factory.begin() as session:
        session.get(Claim, scope[4]).status = "unverified"
    assert guarded.place(scope[0], call.id) == "queued"
    assert provider.placements[0][0] == "+15555550123"
