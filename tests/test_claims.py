"""Claim assertions are separate from exact scoped evidence; fake ingress only."""

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from factories import make_org, make_principal
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from test_agent_loop import FakeModel, proposal
from test_incidents import deliver, incidents, run

from svaar.actions.catalog import build_registry
from svaar.actions.dispatcher import ApprovalPolicy, Dispatcher
from svaar.actions.missions import Mission
from svaar.actions.registry import Channel, ToolContext
from svaar.agent.llm import ModelReply
from svaar.agent.loop import AgentLoop
from svaar.app import create_app
from svaar.config import Settings
from svaar.decisions.service import DecisionService
from svaar.incidents.claims import (
    ClaimConflictError,
    ClaimInput,
    check_claim,
    record_claim,
)
from svaar.incidents.models import Claim, ClaimEvidence
from svaar.incidents.service import IncidentNotFoundError
from svaar.integrations.models import RepoMapping


@pytest.fixture
def scope(session_factory):
    with session_factory.begin() as session:
        org = make_org(session)
        person = make_principal(session, org)
        other = make_org(session)
        stranger = make_principal(session, other)
        session.add(RepoMapping(repository_id=101, installation_id=77, org_id=org.id))
        values = org.id, person.id, other.id, stranger.id
    deliver(session_factory, run())
    incident = incidents(session_factory)[0]
    return (*values, incident.id)


def body(scope, **changes):
    values = dict(
        incident_id=scope[4],
        statement="The build passed.",
        kind="workflow_succeeded",
        run_id=1002,
        run_attempt=1,
        head_sha="a" * 40,
    )
    values.update(changes)
    return ClaimInput(**values)


def save(sessions, scope, **changes):
    with sessions.begin() as session:
        row = record_claim(session, scope[0], scope[1], body(scope, **changes), "source-1")
        return row.id, row.status


def test_absence_and_observed_failure_are_unverified(session_factory, scope):
    identifier, status = save(session_factory, scope, run_id=1001)
    assert status == "unverified"
    with session_factory() as session:
        assert session.get(Claim, identifier).author_id == scope[1]
        assert session.scalar(select(func.count()).select_from(ClaimEvidence)) == 0


def test_exact_success_records_provenance_and_refresh_is_idempotent(session_factory, scope):
    identifier, status = save(session_factory, scope)
    assert status == "unverified"
    deliver(session_factory, run(run_id=1002, conclusion="success"))
    with session_factory.begin() as session:
        assert check_claim(session, scope[0], identifier).status == "confirmed"
        assert check_claim(session, scope[0], identifier).status == "confirmed"
    with session_factory() as session:
        [evidence] = session.scalars(select(ClaimEvidence)).all()
        assert evidence.claim_id == identifier and evidence.stance == "supports"
        assert evidence.rule == "workflow-success-v1"


@pytest.mark.parametrize(
    "change",
    [
        {"run_id": 9999},
        {"run_attempt": 2},
        {"head_sha": "b" * 40},
        {"statement": "The fix merged."},
        {"statement": "Did the build pass?"},
        {"statement": "The build passed and the fix merged."},
        {"statement": "The build has not passed."},
        {"statement": "The run 9999 passed."},
    ],
)
def test_wrong_target_or_model_misclassification_never_confirms(session_factory, scope, change):
    deliver(session_factory, run(run_id=1002, conclusion="success"))
    assert save(session_factory, scope, **change)[1] == "unverified"


def test_merge_claim_is_not_proven_by_successful_ci(session_factory, scope):
    deliver(session_factory, run(run_id=1002, conclusion="success"))
    _, status = save(
        session_factory,
        scope,
        kind="fix_merged",
        run_id=None,
        run_attempt=None,
        statement="The fix merged.",
    )
    assert status == "unverified"


def test_other_incident_success_cannot_support_claim(session_factory, scope):
    deliver(session_factory, run(run_id=1002, branch="other"))
    deliver(session_factory, run(run_id=1003, branch="other", conclusion="success"))
    assert save(session_factory, scope, run_id=1003)[1] == "unverified"


def test_authors_and_reads_are_org_scoped(session_factory, scope):
    with session_factory.begin() as session:
        with pytest.raises(ValueError, match="author"):
            record_claim(session, scope[0], scope[3], body(scope), "source")
    identifier, _ = save(session_factory, scope)
    with session_factory() as session:
        with pytest.raises(LookupError):
            check_claim(session, scope[2], identifier)
        with pytest.raises(IncidentNotFoundError):
            record_claim(session, scope[2], scope[3], body(scope), "source")


def test_source_dedupe_and_conflict_do_not_rewrite_statement(session_factory, scope):
    identifier, _ = save(session_factory, scope)
    assert save(session_factory, scope)[0] == identifier
    with session_factory.begin() as session:
        with pytest.raises(ClaimConflictError):
            record_claim(
                session, scope[0], scope[1], body(scope, statement="Another assertion"), "source-1"
            )
    with session_factory() as session:
        assert session.get(Claim, identifier).statement == "The build passed."
        assert session.scalar(select(func.count()).select_from(Claim)) == 1


def test_concurrent_reprocessing_creates_one_claim(session_factory, scope):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: save(session_factory, scope)[0], range(2)))
    assert results[0] == results[1]


def test_evidence_cannot_be_updated_or_deleted(session_factory, scope):
    deliver(session_factory, run(run_id=1002, conclusion="success"))
    assert save(session_factory, scope)[1] == "confirmed"
    for statement in ["UPDATE evidence SET stance='contradicts'", "DELETE FROM evidence"]:
        with session_factory() as session:
            with pytest.raises(DBAPIError, match="append-only"):
                session.execute(text(statement))
            session.rollback()


def test_real_loop_binds_raw_text_and_dispatcher_rejects_asserted_author(
    session_factory,
    settings,
    scope,
):
    deliver(session_factory, run(run_id=1002, conclusion="success"))
    data = body(scope, statement="model invented this").model_dump(mode="json")
    model = FakeModel(proposal("record_claim", data), ModelReply("Recorded."))
    dispatcher = Dispatcher(build_registry(), ApprovalPolicy.from_settings(settings))
    agent = AgentLoop(model, dispatcher, DecisionService(None, high=0.85, low=0.55))
    context = ToolContext(scope[0], scope[1], Channel.CHAT, None, "real-claim-message")
    try:
        with session_factory.begin() as session:
            assert agent.run(session, context, "The build passed.").reason == "answered"
        with session_factory() as session:
            claim = session.scalar(select(Claim))
            assert claim.statement == "The build passed." and claim.author_id == scope[1]
            assert claim.status == "confirmed"
            result = dispatcher.dispatch(
                session, context, "record_claim", {**data, "author_id": str(scope[3])}
            )
            assert result.output["error"] == "invalid_arguments"
            voice = ToolContext(scope[0], scope[1], Channel.VOICE, Mission.PHONE_VERIFY, "voice")
            result = dispatcher.dispatch(session, voice, "list_claims", {})
            assert result.output["error"] == "not_allowed"
            assert result.output["reason"] == "outside_mission"
    finally:
        agent.close()


def test_operator_claims_view_is_authenticated_and_read_only(
    session_factory,
    database_url,
    scope,
):
    identifier, _ = save(session_factory, scope)
    settings = Settings(_env_file=None, database_url=database_url, operator_token="o" * 32)
    url = f"/api/v1/incidents/{scope[4]}/claims"
    with TestClient(create_app(settings)) as client:
        assert client.get(url).status_code == 401
        response = client.get(url, headers={"Authorization": "Bearer " + "o" * 32})
        assert response.status_code == 200
        assert response.json()["claims"][0]["claim_id"] == str(identifier)
        assert response.json()["claims"][0]["status"] == "unverified"
        assert (
            client.get(
                f"/api/v1/incidents/{uuid.uuid4()}/claims",
                headers={"Authorization": "Bearer " + "o" * 32},
            ).status_code
            == 404
        )
