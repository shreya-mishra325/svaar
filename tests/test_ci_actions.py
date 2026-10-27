"""Durable confirmed CI actions with fake providers and no live mutations."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from test_ci_jobs import scope as scope
from test_incidents import deliver, incidents, run

from svaar.actions.catalog import build_registry
from svaar.actions.dispatcher import ApprovalPolicy, Dispatcher
from svaar.actions.missions import Mission
from svaar.actions.models import ToolStatus
from svaar.actions.registry import Channel, ToolContext
from svaar.identity.models import Principal, Role
from svaar.incidents.models import ObservedEvent
from svaar.integrations.ci_actions import CiActionService
from svaar.integrations.github_actions import (
    ActionReceipt,
    GithubActionRejectedError,
    GithubActionUnknownError,
)
from svaar.integrations.models import CiActionIntent, RepoMapping

pytestmark = pytest.mark.postgres


class Provider:
    def __init__(self, sessions, error=None):
        self.sessions, self.error, self.calls, self.closed = sessions, error, [], 0
        self.assert_idle = True

    def execute(self, action, run_id, run_attempt, head_sha, *, deadline=None):
        # The irreversible boundary is durably visible before any POST.
        if self.assert_idle:
            assert self.sessions.kw["bind"].pool.checkedout() == 0
        with self.sessions() as session:
            assert session.scalar(select(CiActionIntent)).state == "placing"
        self.calls.append((action, run_id, run_attempt, head_sha))
        if self.error:
            raise self.error
        return ActionReceipt(201, "FAKE:123")

    def close(self):
        self.closed += 1


@pytest.fixture
def setup(session_factory, scope):
    with session_factory.begin() as session:
        session.get(Principal, scope[1]).role = Role.LEAD
    deliver(session_factory, run())
    incident = incidents(session_factory)[0]
    provider = Provider(session_factory)
    service = CiActionService(session_factory, lambda *_: provider)
    dispatcher = Dispatcher(
        build_registry(ci_actions=service.execute), ApprovalPolicy(timedelta(minutes=10), 3, False)
    )
    arguments = {
        "incident_id": str(incident.id),
        "repository_id": 101,
        "installation_id": 77,
        "run_id": 1001,
        "run_attempt": 1,
    }
    return scope, provider, dispatcher, arguments


def dispatch(sessions, setup, name, args, *, voice=False):
    scope, _, gate, _ = setup
    context = ToolContext(
        scope[0],
        scope[1],
        Channel.VOICE if voice else Channel.CHAT,
        Mission.CONFIRMATION if voice else None,
        "confirmed-ci",
    )
    with sessions() as session:
        result = gate.dispatch(session, context, name, args)
        session.commit()
        return result


def test_rerun_waits_for_owner_nonce_and_records_receipt(session_factory, setup):
    scope, provider, _, arguments = setup
    pending = dispatch(session_factory, setup, "rerun_workflow", arguments)
    assert pending.status == ToolStatus.CONFIRMATION_REQUIRED and pending.ticket
    assert "1001" in pending.ticket.summary and "77" in pending.ticket.summary
    assert provider.calls == []
    confirmed = dispatch(
        session_factory, setup, "confirm_action", {"code": pending.ticket.nonce}, voice=True
    )
    assert confirmed.status == ToolStatus.SUCCEEDED
    assert confirmed.output["result"]["accepted"]
    assert confirmed.output["result"]["http_status"] == 201
    assert provider.calls == [("rerun_workflow", 1001, 1, "a" * 40)] and provider.closed == 1
    with session_factory() as session:
        intent = session.scalar(select(CiActionIntent))
        assert intent.state == "accepted" and intent.request_id == "FAKE:123"
        assert session.scalar(select(func.count()).select_from(ObservedEvent)) == 1
    repeated = dispatch(
        session_factory, setup, "confirm_action", {"code": pending.ticket.nonce}, voice=True
    )
    assert repeated.status == ToolStatus.DENIED and len(provider.calls) == 1


def test_new_confirmation_cannot_repeat_same_attempt(session_factory, setup):
    provider, args = setup[1], setup[3]
    for _ in range(2):
        pending = dispatch(session_factory, setup, "rerun_workflow", args)
        confirmed = dispatch(
            session_factory, setup, "confirm_action", {"code": pending.ticket.nonce}, voice=True
        )
    assert len(provider.calls) == 1
    assert confirmed.output["result"]["reason"] == "existing_intent_requires_review"


@pytest.mark.parametrize(
    "error,state,status",
    [
        (GithubActionUnknownError("simulated"), "unknown", ToolStatus.OUTCOME_UNKNOWN),
        (GithubActionRejectedError("simulated"), "rejected", ToolStatus.FAILED),
    ],
)
def test_provider_rejection_and_unknown_are_durable_and_not_retried(
    session_factory, setup, error, state, status
):
    provider, args = setup[1], setup[3]
    provider.error = error
    pending = dispatch(session_factory, setup, "rerun_workflow", args)
    result = dispatch(
        session_factory, setup, "confirm_action", {"code": pending.ticket.nonce}, voice=True
    )
    assert result.status == status
    with session_factory() as session:
        assert session.scalar(select(CiActionIntent)).state == state
    pending = dispatch(session_factory, setup, "rerun_workflow", args)
    dispatch(session_factory, setup, "confirm_action", {"code": pending.ticket.nonce}, voice=True)
    assert len(provider.calls) == 1


@pytest.mark.parametrize("change", ["role", "mapping", "incident"])
def test_execution_rechecks_scope_and_permissions(session_factory, setup, change):
    scope, provider, _, args = setup
    pending = dispatch(session_factory, setup, "rerun_workflow", args)
    with session_factory.begin() as session:
        if change == "role":
            session.get(Principal, scope[1]).role = Role.DEV
        elif change == "mapping":
            session.get(RepoMapping, 101).installation_id = 88
        else:
            from svaar.incidents.models import Incident

            session.get(Incident, uuid.UUID(args["incident_id"])).state = "resolved"
    result = dispatch(
        session_factory, setup, "confirm_action", {"code": pending.ticket.nonce}, voice=True
    )
    assert provider.calls == []
    assert result.status == ToolStatus.DENIED or not result.output["result"]["accepted"]


def test_no_writer_registered_by_default():
    registry = build_registry()
    assert "rerun_workflow" not in registry and "cancel_run" not in registry


def test_concurrent_confirmations_still_create_one_mutation_intent(session_factory, setup):
    from concurrent.futures import ThreadPoolExecutor

    # Other concurrent dispatches may own connections; isolated tests check idle I/O.
    setup[1].assert_idle = False
    tickets = [
        dispatch(session_factory, setup, "rerun_workflow", setup[3]).ticket for _ in range(2)
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda ticket: dispatch(
                    session_factory, setup, "confirm_action", {"code": ticket.nonce}, voice=True
                ),
                tickets,
            )
        )
    assert len(setup[1].calls) == 1
    assert sum(bool(row.output.get("result", {}).get("accepted")) for row in results) == 1
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(CiActionIntent)) == 1


def test_crash_leaves_placing_and_new_nonce_cannot_repeat_post(session_factory, setup):
    setup[1].error = KeyboardInterrupt()
    pending = dispatch(session_factory, setup, "rerun_workflow", setup[3])
    with pytest.raises(KeyboardInterrupt):
        dispatch(
            session_factory, setup, "confirm_action", {"code": pending.ticket.nonce}, voice=True
        )
    with session_factory() as session:
        assert session.scalar(select(CiActionIntent)).state == "placing"
    setup[1].error = None
    pending = dispatch(session_factory, setup, "rerun_workflow", setup[3])
    result = dispatch(
        session_factory, setup, "confirm_action", {"code": pending.ticket.nonce}, voice=True
    )
    assert result.output["result"]["reason"] == "existing_intent_requires_review"
    assert len(setup[1].calls) == 1


def test_operator_can_inspect_receipt_but_cannot_trigger_retry(
    database_url, session_factory, setup
):
    from fastapi.testclient import TestClient

    from svaar.app import create_app
    from svaar.config import Settings

    pending = dispatch(session_factory, setup, "rerun_workflow", setup[3])
    dispatch(session_factory, setup, "confirm_action", {"code": pending.ticket.nonce}, voice=True)
    with session_factory() as session:
        identifier = session.scalar(select(CiActionIntent.id))
    settings = Settings(_env_file=None, database_url=database_url, operator_token="o" * 32)
    with TestClient(create_app(settings)) as client:
        path = f"/api/v1/ci-actions/{identifier}"
        assert client.get(path).status_code == 401
        receipt = client.get(path, headers={"Authorization": "Bearer " + "o" * 32})
        assert receipt.status_code == 200 and receipt.json()["state"] == "accepted"
        assert client.post(path, headers={"Authorization": "Bearer " + "o" * 32}).status_code == 405
