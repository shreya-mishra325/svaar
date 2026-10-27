"""Trusted resolution tools, snapshot freshness and confirmed document approval."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from factories import make_org, make_principal
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_incidents import deliver, incidents, run
from test_resolution_api import DEMO
from test_resolution_validator import BASE

from svaar.actions.catalog import build_registry
from svaar.actions.dispatcher import ApprovalPolicy, Dispatcher
from svaar.actions.missions import Mission
from svaar.actions.models import ToolStatus
from svaar.actions.registry import Channel, ToolContext
from svaar.app import create_app
from svaar.config import Settings
from svaar.identity.models import Principal, Role
from svaar.incidents.models import ObservedEvent
from svaar.integrations.models import RepoMapping
from svaar.replay.models import ReplayRun
from svaar.resolution import policy
from svaar.resolution.constraints import Constraints
from svaar.resolution.models import ExceptionDraft, Negotiation, StandingConstraint

pytestmark = pytest.mark.postgres
AUTH = {"Authorization": "Bearer " + "o" * 32}


@pytest.fixture
def scope(session_factory):
    with session_factory.begin() as session:
        org = make_org(session)
        lead = make_principal(session, org, Role.LEAD)
        other = make_principal(session, make_org(session), Role.ADMIN)
        session.add(RepoMapping(repository_id=101, installation_id=77, org_id=org.id))
        policy.replace_constraints(session, org.id, BASE, expected_revision=0)
        ids = org.id, lead.id, other.org_id, other.id
    deliver(session_factory, run())
    return (*ids, incidents(session_factory)[0].id)


@pytest.fixture
def dispatcher():
    return Dispatcher(build_registry(), ApprovalPolicy(timedelta(minutes=10), 3, False))


def context(scope, *, voice=False, foreign=False):
    org, principal = (scope[2], scope[3]) if foreign else (scope[0], scope[1])
    return ToolContext(
        org,
        principal,
        Channel.VOICE if voice else Channel.CHAT,
        Mission.CONFIRMATION if voice else None,
        "resolution-turn",
    )


def dispatch(sessions, dispatcher, scope, tool, args, **kwargs):
    with sessions() as session:
        result = dispatcher.dispatch(session, context(scope, **kwargs), tool, args)
        session.commit()
        return result


def negotiate(sessions, dispatcher, scope, **kwargs):
    return dispatch(
        sessions,
        dispatcher,
        scope,
        "start_negotiation",
        {"incident_id": str(scope[4]), "proposal": DEMO.model_dump(mode="json")},
        **kwargs,
    )


def test_tool_uses_standing_snapshot_and_exports_changes(session_factory, dispatcher, scope):
    result = negotiate(session_factory, dispatcher, scope)
    assert result.status == ToolStatus.SUCCEEDED and result.output["accepted"]
    assert [row["valid"] for row in result.output["rounds"]] == [False, True]
    with session_factory() as session:
        negotiation = session.get(Negotiation, uuid.UUID(result.output["negotiation_id"]))
        draft = session.get(ExceptionDraft, uuid.UUID(result.output["draft_id"]))
        assert negotiation.constraints_revision == draft.constraints_revision == 1
        assert negotiation.constraints == BASE.model_dump(mode="json")
        assert draft.content["before"] == negotiation.initial_proposal
        assert draft.content["after"] == negotiation.accepted_proposal
        assert {change["field"] for change in draft.content["changes"]} == {"start"}
        assert draft.state == "draft"


def test_model_cannot_supply_constraints_or_approval_names(session_factory, dispatcher, scope):
    args = {
        "incident_id": str(scope[4]),
        "proposal": DEMO.model_dump(mode="json"),
        "constraints": Constraints().model_dump(mode="json"),
    }
    result = dispatch(session_factory, dispatcher, scope, "start_negotiation", args)
    assert result.status == ToolStatus.INVALID_ARGUMENTS
    args.pop("constraints")
    args["proposal"]["approvals"] = ["release-lead"]
    result = dispatch(session_factory, dispatcher, scope, "start_negotiation", args)
    assert result.output == {"accepted": False, "reason": "unverified_approvals"}
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Negotiation)) == 0


def test_missing_standing_policy_has_no_defaults(session_factory, dispatcher, scope):
    from sqlalchemy import delete

    with session_factory.begin() as session:
        session.execute(delete(StandingConstraint))
    result = negotiate(session_factory, dispatcher, scope)
    assert result.output["reason"] == "constraints_not_configured"


def test_foreign_incident_and_role_are_denied(session_factory, dispatcher, scope):
    assert (
        negotiate(session_factory, dispatcher, scope, foreign=True).output["reason"]
        == "constraints_not_configured"
    )
    with session_factory.begin() as session:
        session.get(Principal, scope[1]).role = Role.DEV
    assert negotiate(session_factory, dispatcher, scope).status == ToolStatus.DENIED


def test_policy_update_is_atomic_and_snapshot_stays_historical(session_factory, dispatcher, scope):
    result = negotiate(session_factory, dispatcher, scope)
    with session_factory.begin() as session:
        assert (
            policy.replace_constraints(session, scope[0], Constraints(), expected_revision=1) == 2
        )
    with session_factory() as session:
        with pytest.raises(policy.ConstraintRevisionConflictError):
            policy.replace_constraints(session, scope[0], BASE, expected_revision=1)
        session.rollback()
        rules, revision = policy.load_constraints(session, scope[0])
        assert rules == Constraints() and revision == 2
        stored = session.get(Negotiation, uuid.UUID(result.output["negotiation_id"]))
        assert stored.constraints == BASE.model_dump(mode="json")


def test_concurrent_policy_updates_have_one_winner(session_factory, scope):
    def update(_):
        try:
            with session_factory.begin() as session:
                return policy.replace_constraints(session, scope[0], BASE, expected_revision=1)
        except policy.ConstraintRevisionConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(map(str, pool.map(update, range(2)))) == ["2", "conflict"]


def test_exception_waits_for_owner_cross_channel_nonce(session_factory, dispatcher, scope):
    result = negotiate(session_factory, dispatcher, scope)
    pending = dispatch(
        session_factory,
        dispatcher,
        scope,
        "approve_exception",
        {"draft_id": result.output["draft_id"]},
    )
    assert pending.status == ToolStatus.CONFIRMATION_REQUIRED and pending.ticket
    with session_factory() as session:
        assert session.get(ExceptionDraft, uuid.UUID(result.output["draft_id"])).state == "draft"
    assert (
        dispatch(
            session_factory, dispatcher, scope, "confirm_action", {"code": pending.ticket.nonce}
        ).status
        == ToolStatus.DENIED
    )
    assert (
        dispatch(
            session_factory,
            dispatcher,
            scope,
            "confirm_action",
            {"code": pending.ticket.nonce},
            voice=True,
            foreign=True,
        ).status
        == ToolStatus.DENIED
    )
    confirmed = dispatch(
        session_factory,
        dispatcher,
        scope,
        "confirm_action",
        {"code": pending.ticket.nonce},
        voice=True,
    )
    assert confirmed.output["result"]["approved"]
    with session_factory() as session:
        draft = session.get(ExceptionDraft, uuid.UUID(result.output["draft_id"]))
        assert draft.approved_by == scope[1] and draft.approved_at
    repeated = dispatch(
        session_factory,
        dispatcher,
        scope,
        "confirm_action",
        {"code": pending.ticket.nonce},
        voice=True,
    )
    assert repeated.status == ToolStatus.DENIED


def test_policy_change_between_nonce_and_execution_requires_renegotiation(
    session_factory, dispatcher, scope
):
    result = negotiate(session_factory, dispatcher, scope)
    pending = dispatch(
        session_factory,
        dispatcher,
        scope,
        "approve_exception",
        {"draft_id": result.output["draft_id"]},
    )
    with session_factory.begin() as session:
        policy.replace_constraints(session, scope[0], BASE, expected_revision=1)
    confirmed = dispatch(
        session_factory,
        dispatcher,
        scope,
        "confirm_action",
        {"code": pending.ticket.nonce},
        voice=True,
    )
    assert confirmed.output["result"] == {"approved": False, "reason": "renegotiation_required"}
    with session_factory() as session:
        assert session.get(ExceptionDraft, uuid.UUID(result.output["draft_id"])).state == "draft"


def replay_args(scope, negotiation_id):
    return {
        "incident_id": str(scope[4]),
        "negotiation_id": negotiation_id,
        "scenario": {"steps": [{"name": "test", "recorded": "failure"}], "fixes": ["test"]},
    }


def test_agent_replay_is_labelled_and_never_mutates_facts(
    session_factory, dispatcher, scope, monkeypatch
):
    import httpx

    monkeypatch.setattr(httpx.Client, "send", lambda *_args, **_kwargs: pytest.fail("network"))
    accepted = negotiate(session_factory, dispatcher, scope)
    with session_factory() as session:
        before = session.scalar(select(func.count()).select_from(ObservedEvent))
    result = dispatch(
        session_factory,
        dispatcher,
        scope,
        "request_replay",
        replay_args(scope, accepted.output["negotiation_id"]),
    )
    assert result.output["simulated"] and result.output["kind"] == "simulated"
    assert result.output["result"]["conclusion"] == "success"
    assert "not evidence" in result.output["label"]
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ObservedEvent)) == before
        replay = session.get(ReplayRun, uuid.UUID(result.output["replay_id"]))
        assert str(replay.negotiation_id) == accepted.output["negotiation_id"]


def test_replay_requires_current_plan_for_same_incident(session_factory, dispatcher, scope):
    accepted = negotiate(session_factory, dispatcher, scope)
    args = replay_args(scope, accepted.output["negotiation_id"])
    assert (
        dispatch(session_factory, dispatcher, scope, "request_replay", args, foreign=True).output[
            "simulated"
        ]
        is False
    )
    with session_factory.begin() as session:
        policy.replace_constraints(session, scope[0], BASE, expected_revision=1)
    result = dispatch(session_factory, dispatcher, scope, "request_replay", args)
    assert result.output["reason"] == "current_validated_plan_required"


def test_constraint_routes_are_operator_only_and_revision_checked(
    database_url, session_factory, scope
):
    settings = Settings(_env_file=None, database_url=database_url, operator_token="o" * 32)
    path = f"/api/v1/orgs/{scope[0]}/constraints"
    with TestClient(create_app(settings)) as client:
        assert client.get(path).status_code == 401
        assert client.get(path, headers=AUTH).json()["revision"] == 1
        body = {"expected_revision": 1, "constraints": BASE.model_dump(mode="json")}
        assert client.put(path, json=body).status_code == 401
        assert client.put(path, headers=AUTH, json=body).json()["revision"] == 2
        assert client.put(path, headers=AUTH, json=body).status_code == 409
        assert (
            client.put(path, headers=AUTH, json={**body, "expected_revision": True}).status_code
            == 422
        )


def test_draft_content_cannot_change_after_export(session_factory, dispatcher, scope):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    result = negotiate(session_factory, dispatcher, scope)
    with session_factory() as session:
        with pytest.raises(DBAPIError):
            session.execute(
                text("UPDATE exception_drafts SET content = '{}'::jsonb WHERE id = :id"),
                {"id": result.output["draft_id"]},
            )
            session.flush()


def test_role_revocation_before_confirmation_prevents_approval(session_factory, dispatcher, scope):
    result = negotiate(session_factory, dispatcher, scope)
    pending = dispatch(
        session_factory,
        dispatcher,
        scope,
        "approve_exception",
        {"draft_id": result.output["draft_id"]},
    )
    with session_factory.begin() as session:
        session.get(Principal, scope[1]).role = Role.DEV
    confirmed = dispatch(
        session_factory,
        dispatcher,
        scope,
        "confirm_action",
        {"code": pending.ticket.nonce},
        voice=True,
    )
    assert confirmed.status == ToolStatus.DENIED
    with session_factory() as session:
        assert session.get(ExceptionDraft, uuid.UUID(result.output["draft_id"])).state == "draft"


def test_foreign_draft_cannot_be_approved(session_factory, dispatcher, scope):
    result = negotiate(session_factory, dispatcher, scope)
    with session_factory.begin() as session:
        policy.replace_constraints(session, scope[2], BASE, expected_revision=0)
    pending = dispatch(
        session_factory,
        dispatcher,
        scope,
        "approve_exception",
        {"draft_id": result.output["draft_id"]},
        foreign=True,
    )
    confirmed = dispatch(
        session_factory,
        dispatcher,
        scope,
        "confirm_action",
        {"code": pending.ticket.nonce},
        foreign=True,
        voice=True,
    )
    assert confirmed.output["result"] == {"approved": False, "reason": "not_found"}
