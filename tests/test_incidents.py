"""Incident grouping, ordered timelines and incident tools over real PostgreSQL ingestion."""

import json
import threading
import uuid
from datetime import timedelta

import pytest
from factories import make_org, make_principal
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from svaar.actions.catalog import build_registry
from svaar.actions.dispatcher import ApprovalPolicy, Dispatcher
from svaar.actions.missions import Mission
from svaar.actions.models import ToolStatus
from svaar.actions.registry import Channel, ToolContext
from svaar.app import create_app
from svaar.config import Settings
from svaar.identity.models import Org, Role
from svaar.incidents import service
from svaar.incidents.models import Incident, IncidentEvent, IncidentState
from svaar.integrations.github import ingest_delivery
from svaar.integrations.models import RepoMapping

pytestmark = pytest.mark.postgres
OPERATOR = "o" * 32


@pytest.fixture
def org_id(session_factory):
    with session_factory.begin() as session:
        org = make_org(session)
        session.add(RepoMapping(repository_id=101, installation_id=77, org_id=org.id))
        return org.id


def run(
    run_id=1001,
    conclusion="failure",
    at="2026-10-23T10:00:00Z",
    branch="main",
    workflow_id=55,
    action="completed",
    attempt=1,
):
    status = {"completed": "completed", "in_progress": "in_progress", "requested": "queued"}
    return json.dumps(
        {
            "action": action,
            "repository": {"id": 101},
            "installation": {"id": 77},
            "workflow_run": {
                "id": run_id,
                "run_attempt": attempt,
                "head_sha": "a" * 40,
                "status": status[action],
                "conclusion": conclusion if action == "completed" else None,
                "updated_at": at,
                "workflow_id": workflow_id,
                "name": "Deploy",
                "head_branch": branch,
            },
        }
    ).encode()


def deliver(sessions, raw, delivery=None):
    return ingest_delivery(sessions, delivery or uuid.uuid4(), "workflow_run", raw)


def incidents(sessions):
    with sessions() as session:
        return list(session.scalars(select(Incident).order_by(Incident.opened_at)))


def test_failure_opens_incident_with_its_event(session_factory, org_id):
    assert deliver(session_factory, run()) == "accepted"
    [incident] = incidents(session_factory)
    assert incident.org_id == org_id and incident.state == "open"
    assert (incident.workflow_name, incident.head_branch, incident.failure_count) == (
        "Deploy",
        "main",
        1,
    )
    with session_factory() as session:
        [entry] = service.timeline(session, org_id, incident.id)
    assert entry.kind == "workflow_run.completed" and entry.conclusion == "failure"


@pytest.mark.parametrize("conclusion", ["success", "cancelled", "skipped"])
def test_non_failures_never_open_incidents(session_factory, org_id, conclusion):
    deliver(session_factory, run(conclusion=conclusion))
    assert incidents(session_factory) == []


def test_reruns_join_the_active_incident_in_occurrence_order(session_factory, org_id):
    # Delivered out of order: the later failure arrives first.
    deliver(session_factory, run(run_id=2, at="2026-10-23T10:20:00Z"))
    deliver(session_factory, run(run_id=1, at="2026-10-23T10:00:00Z"))
    deliver(session_factory, run(run_id=3, action="in_progress", at="2026-10-23T10:30:00Z"))
    deliver(session_factory, run(run_id=3, conclusion="success", at="2026-10-23T10:40:00Z"))
    [incident] = incidents(session_factory)
    assert incident.failure_count == 2
    with session_factory() as session:
        entries = service.timeline(session, org_id, incident.id)
    assert [(e.run_id, e.conclusion) for e in entries] == [
        (1, "failure"),
        (2, "failure"),
        (3, None),
        (3, "success"),
    ]
    # A success records evidence only; it never resolves the incident by itself.
    assert incident.state == "open"


def test_branch_and_workflow_separate_incidents(session_factory, org_id):
    deliver(session_factory, run(run_id=1, branch="main"))
    deliver(session_factory, run(run_id=2, branch="release"))
    deliver(session_factory, run(run_id=3, workflow_id=99))
    assert len(incidents(session_factory)) == 3


def test_redelivery_does_not_double_count(session_factory, org_id):
    raw = run()
    deliver(session_factory, raw)
    assert deliver(session_factory, raw) == "accepted"  # new delivery ID, same transition
    [incident] = incidents(session_factory)
    assert incident.failure_count == 1
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(IncidentEvent)) == 1


def test_concurrent_failures_share_one_incident(session_factory, org_id):
    barrier = threading.Barrier(4)
    errors = []

    def worker(run_id):
        barrier.wait()
        try:
            deliver(session_factory, run(run_id=run_id, at=f"2026-10-23T10:0{run_id}:00Z"))
        except Exception as exc:  # pragma: no cover - surfaced by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(1, 5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    [incident] = incidents(session_factory)
    assert incident.failure_count == 4


def test_lookups_are_org_scoped(session_factory, org_id):
    deliver(session_factory, run())
    [incident] = incidents(session_factory)
    with session_factory.begin() as session:
        other = make_org(session, "Other").id
    with session_factory() as session:
        with pytest.raises(service.IncidentNotFoundError):
            service.timeline(session, other, incident.id)
        assert service.list_incidents(session, other) == []


def test_acknowledge_is_idempotent_and_failures_still_join(session_factory, org_id):
    deliver(session_factory, run(run_id=1))
    [incident] = incidents(session_factory)
    with session_factory.begin() as session:
        principal_id = make_principal(session, session.get(Org, org_id)).id
    with session_factory.begin() as session:
        acked, changed = service.acknowledge(session, org_id, incident.id, principal_id)
        assert changed and acked.state == "acknowledged" and acked.acknowledged_by == principal_id
    with session_factory.begin() as session:
        _, changed = service.acknowledge(session, org_id, incident.id, principal_id)
        assert not changed
    deliver(session_factory, run(run_id=2, at="2026-10-23T11:00:00Z"))
    [incident] = incidents(session_factory)
    assert incident.failure_count == 2 and incident.state == IncidentState.ACKNOWLEDGED


# Tools through the actions dispatcher.


@pytest.fixture
def dispatcher():
    return Dispatcher(build_registry(), ApprovalPolicy(timedelta(minutes=10), 3, False))


@pytest.fixture
def principal(session_factory, org_id):
    with session_factory.begin() as session:
        return make_principal(session, session.get(Org, org_id), Role.DEV)


def context(principal, channel=Channel.CHAT, mission=None):
    return ToolContext(principal.org_id, principal.id, channel, mission, "turn-1")


def test_get_timeline_tool_defaults_to_latest_incident(session_factory, dispatcher, principal):
    deliver(session_factory, run(run_id=1))
    deliver(session_factory, run(run_id=2, at="2026-10-23T10:05:00Z"))
    with session_factory.begin() as session:
        result = dispatcher.dispatch(session, context(principal), "get_timeline", {})
    assert result.status is ToolStatus.SUCCEEDED
    assert result.output["found"] and result.output["incident"]["failures"] == 2
    assert [event["run_id"] for event in result.output["events"]] == [1, 2]


def test_timeline_tool_on_escalation_call(session_factory, dispatcher, principal):
    deliver(session_factory, run())
    voice = context(principal, Channel.VOICE, Mission.ESCALATION)
    with session_factory.begin() as session:
        assert dispatcher.dispatch(session, voice, "get_timeline", {}).output["found"]
        # list_incidents is chat-only and outside the escalation mission.
        denied = dispatcher.dispatch(session, voice, "list_incidents", {})
    assert denied.status is ToolStatus.DENIED


def test_tools_handle_missing_and_foreign_incidents(session_factory, dispatcher, principal):
    with session_factory.begin() as session:
        empty = dispatcher.dispatch(session, context(principal), "get_timeline", {})
        foreign = dispatcher.dispatch(
            session, context(principal), "get_timeline", {"incident_id": str(uuid.uuid4())}
        )
    assert empty.output == {"found": False} and foreign.output == {"found": False}


def test_acknowledge_and_list_tools(session_factory, dispatcher, principal):
    deliver(session_factory, run())
    with session_factory.begin() as session:
        listed = dispatcher.dispatch(session, context(principal), "list_incidents", {})
        acked = dispatcher.dispatch(session, context(principal), "acknowledge_incident", {})
    assert len(listed.output["incidents"]) == 1
    assert acked.output["acknowledged"] and acked.output["incident"]["state"] == "acknowledged"


# Operator route.


@pytest.fixture
def operator_client(database_url, session_factory):
    settings = Settings(
        _env_file=None, database_url=database_url, environment="test", operator_token=OPERATOR
    )
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        yield client


def test_operator_timeline_route(session_factory, org_id, operator_client):
    deliver(session_factory, run())
    [incident] = incidents(session_factory)
    url = f"/api/v1/incidents/{incident.id}/timeline"
    assert operator_client.get(url).status_code == 401
    auth = {"Authorization": f"Bearer {OPERATOR}"}
    body = operator_client.get(url, headers=auth).json()
    assert body["incident"]["failure_count"] == 1 and len(body["events"]) == 1
    missing = operator_client.get(f"/api/v1/incidents/{uuid.uuid4()}/timeline", headers=auth)
    assert missing.status_code == 404
