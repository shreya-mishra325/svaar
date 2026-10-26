"""Negotiations persist every round; operator routes run and re-validate proposals."""

import uuid

import pytest
from factories import make_org
from fastapi.testclient import TestClient
from test_resolution_validator import BASE, at, proposal

from svaar.app import create_app
from svaar.config import Settings
from svaar.incidents.service import IncidentNotFoundError
from svaar.resolution import service

pytestmark = pytest.mark.postgres
OPERATOR = "o" * 32
AUTH = {"Authorization": f"Bearer {OPERATOR}"}
DEMO = proposal(start=at(11.5), duration_minutes=120, engineer="meera")


@pytest.fixture
def org_id(session_factory):
    with session_factory.begin() as session:
        return make_org(session).id


def test_rounds_are_persisted_in_order(session_factory, org_id):
    with session_factory.begin() as session:
        negotiation, outcome = service.start_negotiation(
            session, org_id=org_id, constraints=BASE, proposal=DEMO
        )
        negotiation_id = negotiation.id
    with session_factory() as session:
        stored, rounds = service.get_negotiation(session, org_id, negotiation_id)
    assert stored.state == "accepted" and len(rounds) == len(outcome.rounds) == 2
    assert [r.valid for r in rounds] == [False, True]
    assert {v["code"] for v in rounds[0].violations} == {
        "deploy_capacity",
        "freeze_window",
        "engineer_off_shift",
    }
    assert rounds[1].revised_by == ["release", "capacity"]
    assert stored.accepted_proposal["start"].startswith("2026-10-28T14:00")


def test_lookups_and_incidents_are_org_scoped(session_factory, org_id):
    with session_factory.begin() as session:
        negotiation, _ = service.start_negotiation(
            session, org_id=org_id, constraints=BASE, proposal=proposal()
        )
        negotiation_id = negotiation.id
        other = make_org(session, "Other").id
    with session_factory() as session:
        with pytest.raises(service.NegotiationNotFoundError):
            service.get_negotiation(session, other, negotiation_id)
        with pytest.raises(IncidentNotFoundError):
            service.start_negotiation(
                session,
                org_id=org_id,
                constraints=BASE,
                proposal=proposal(),
                incident_id=uuid.uuid4(),
            )


@pytest.fixture
def client(database_url, session_factory):
    settings = Settings(
        _env_file=None, database_url=database_url, environment="test", operator_token=OPERATOR
    )
    with TestClient(create_app(settings), raise_server_exceptions=False) as test_client:
        yield test_client


def body(org_id, start):
    return {
        "org_id": str(org_id),
        "constraints": BASE.model_dump(mode="json"),
        "proposal": DEMO.model_copy(update={"start": start}).model_dump(mode="json"),
    }


def test_operator_negotiation_routes(client, org_id):
    assert client.post("/api/v1/negotiations", json=body(org_id, at(11.5))).status_code == 401
    created = client.post("/api/v1/negotiations", json=body(org_id, at(11.5)), headers=AUTH)
    assert created.status_code == 201
    data = created.json()
    assert data["state"] == "accepted" and [r["valid"] for r in data["rounds"]] == [False, True]

    read = client.get(f"/api/v1/negotiations/{data['id']}", headers=AUTH).json()
    assert read == data

    check = f"/api/v1/negotiations/{data['id']}/validate"
    rejected = client.post(check, json=DEMO.model_dump(mode="json"), headers=AUTH).json()
    accepted = client.post(check, json=data["accepted_proposal"], headers=AUTH).json()
    assert not rejected["valid"] and len(rejected["violations"]) == 3
    assert accepted == {"valid": True, "violations": []}


def test_routes_reject_unknown_org_and_naive_times(client):
    unknown = client.post("/api/v1/negotiations", json=body(uuid.uuid4(), at(15)), headers=AUTH)
    assert unknown.status_code == 404
    naive = body(uuid.uuid4(), at(15))
    naive["proposal"]["start"] = "2026-10-28T15:00:00"
    assert client.post("/api/v1/negotiations", json=naive, headers=AUTH).status_code == 422
    missing = client.get(f"/api/v1/negotiations/{uuid.uuid4()}", headers=AUTH)
    assert missing.status_code == 404
