"""Replay is simulated, isolated from observed events, and never reaches a provider."""

import ast
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from test_incidents import deliver, incidents, run

from svaar.app import create_app
from svaar.config import Settings
from svaar.incidents.models import Incident, ObservedEvent
from svaar.incidents.service import IncidentNotFoundError
from svaar.replay import service
from svaar.replay.models import ReplayRun
from svaar.replay.simulator import LABEL, Scenario, Step, simulate

OPERATOR = "o" * 32
PIPELINE = (
    Step(name="build", recorded="success", seconds=90),
    Step(name="test", recorded="failure", seconds=120),
    Step(name="deploy", recorded="success", seconds=60),
)


def test_unfixed_pipeline_fails_where_it_failed_and_stops():
    result = simulate(Scenario(steps=PIPELINE))
    assert result.conclusion == "failure" and result.kind == "simulated"
    assert [(s.name, s.outcome) for s in result.steps] == [
        ("build", "success"),
        ("test", "failure"),
        ("deploy", "not_run"),
    ]


def test_corrected_pipeline_is_a_labelled_simulated_success():
    result = simulate(Scenario(steps=PIPELINE, fixes={"test"}, correction="pin dependency"))
    assert result.conclusion == "success"
    assert [s.offset_seconds for s in result.steps] == [0, 90, 210]
    assert result.label == LABEL and "not evidence of production recovery" in result.label


@pytest.mark.parametrize(
    "kwargs",
    [
        {"steps": ()},
        {"steps": PIPELINE, "fixes": {"lint"}},
        {"steps": (PIPELINE[0], PIPELINE[0])},
    ],
)
def test_invalid_scenarios_are_rejected(kwargs):
    with pytest.raises(ValidationError):
        Scenario(**kwargs)


def test_replay_package_imports_no_provider_or_network_code():
    """Static proof: replay cannot reach GitHub, Jira, Bolna or the network."""
    banned = ("svaar.integrations", "svaar.voice", "svaar.agent", "httpx", "requests", "socket")
    package = Path(__file__).parents[1] / "src" / "svaar" / "replay"
    for source in package.glob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert not name.startswith(banned), f"{source.name} imports {name}"


# Database-backed isolation.


@pytest.fixture
def incident(session_factory):
    from test_incidents import RepoMapping, make_org

    with session_factory.begin() as session:
        org = make_org(session)
        session.add(RepoMapping(repository_id=101, installation_id=77, org_id=org.id))
    deliver(session_factory, run())
    [found] = incidents(session_factory)
    return found


@pytest.mark.postgres
def test_replay_never_writes_events_or_changes_the_incident(session_factory, incident, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("replay attempted a network request")

    monkeypatch.setattr(httpx.Client, "send", no_network)
    with session_factory() as session:
        events_before = session.scalar(select(func.count()).select_from(ObservedEvent))
    with session_factory.begin() as session:
        replay = service.run_replay(
            session, incident.org_id, incident.id, Scenario(steps=PIPELINE, fixes={"test"})
        )
        assert replay.result["conclusion"] == "success" and replay.kind == "simulated"
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ObservedEvent)) == events_before
        after = session.get(Incident, incident.id)
        assert (after.state, after.failure_count) == (incident.state, incident.failure_count)
        assert len(service.list_replays(session, incident.org_id, incident.id)) == 1


@pytest.mark.postgres
def test_database_refuses_non_simulated_replay_rows(session_factory, incident):
    with session_factory() as session:
        session.add(
            ReplayRun(
                org_id=incident.org_id,
                incident_id=incident.id,
                kind="observed",
                scenario={},
                result={},
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()


@pytest.mark.postgres
def test_replay_is_org_scoped(session_factory, incident):
    with session_factory.begin() as session:
        with pytest.raises(IncidentNotFoundError):
            service.run_replay(session, uuid.uuid4(), incident.id, Scenario(steps=PIPELINE))
    with session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM replay_runs")) == 0


@pytest.mark.postgres
def test_operator_replay_route(database_url, session_factory, incident):
    settings = Settings(
        _env_file=None, database_url=database_url, environment="test", operator_token=OPERATOR
    )
    body = Scenario(steps=PIPELINE, fixes={"test"}).model_dump(mode="json")
    url = f"/api/v1/incidents/{incident.id}/replay"
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        assert client.post(url, json=body).status_code == 401
        created = client.post(url, json=body, headers={"Authorization": f"Bearer {OPERATOR}"})
        missing = client.post(
            f"/api/v1/incidents/{uuid.uuid4()}/replay",
            json=body,
            headers={"Authorization": f"Bearer {OPERATOR}"},
        )
    assert created.status_code == 201
    data = created.json()
    assert data["kind"] == "simulated" and data["result"]["label"] == LABEL
    assert missing.status_code == 404
