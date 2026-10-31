"""Operator-opened incidents: scoped, deduplicated, owner-alerted and joinable by CI."""

import uuid

import pytest
from factories import make_org, make_principal
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_incidents import chat_route, deliver, incidents, run

from svaar.agent.models import OutboxMessage
from svaar.app import create_app
from svaar.config import Settings
from svaar.identity.models import Role
from svaar.incidents.models import Incident, IncidentEvent, ObservedEvent
from svaar.integrations.models import RepoMapping

pytestmark = pytest.mark.postgres
TOKEN = "o" * 32
AUTH = {"Authorization": "Bearer " + TOKEN}


@pytest.fixture
def scope(session_factory):
    with session_factory.begin() as session:
        org = make_org(session)
        owner = chat_route(session, org, Role.DEV, "manual-owner")
        session.add(
            RepoMapping(
                repository_id=101, installation_id=77, org_id=org.id, owner_principal_id=owner
            )
        )
        return org.id, owner


@pytest.fixture
def client(database_url):
    settings = Settings(_env_file=None, database_url=database_url, operator_token=TOKEN)
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        yield client


def body(scope, **changes):
    values = {
        "org_id": str(scope[0]),
        "repository_id": 101,
        "workflow_id": 55,
        "workflow_name": "Deploy",
        "head_branch": "main",
    }
    values.update(changes)
    return values


def alerts(sessions):
    with sessions() as session:
        return session.scalars(
            select(OutboxMessage.notification_key).where(
                OutboxMessage.notification_key.like("incident-opened:%")
            )
        ).all()


def test_operator_opens_one_owned_incident_and_alerts_the_owner(session_factory, scope, client):
    response = client.post("/api/v1/incidents", json=body(scope), headers=AUTH)
    assert response.status_code == 201
    created = response.json()
    assert created["state"] == "open" and created["owner_principal_id"] == str(scope[1])
    assert alerts(session_factory) == [f"incident-opened:{created['id']}:{scope[1]}"]
    again = client.post("/api/v1/incidents", json=body(scope), headers=AUTH)
    assert again.status_code == 409
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Incident)) == 1
        # Nothing observed is fabricated for a manual report.
        assert session.scalar(select(func.count()).select_from(ObservedEvent)) == 0


def test_later_ci_failure_joins_the_manual_incident(session_factory, scope, client):
    created = client.post("/api/v1/incidents", json=body(scope), headers=AUTH).json()
    assert deliver(session_factory, run()) == "accepted"
    [incident] = incidents(session_factory)
    assert str(incident.id) == created["id"] and incident.failure_count == 2
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(IncidentEvent)) == 1
    assert len(alerts(session_factory)) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"repository_id": 999},
        {"org_id": str(uuid.uuid4())},
        {"owner_principal_id": str(uuid.uuid4())},
    ],
)
def test_unmapped_or_foreign_scope_is_refused(session_factory, scope, client, changes):
    response = client.post("/api/v1/incidents", json=body(scope, **changes), headers=AUTH)
    assert response.status_code == 404
    assert incidents(session_factory) == []


def test_foreign_principal_cannot_own_and_auth_is_required(session_factory, scope, client):
    with session_factory.begin() as session:
        stranger = make_principal(session, make_org(session)).id
    foreign = client.post(
        "/api/v1/incidents", json=body(scope, owner_principal_id=str(stranger)), headers=AUTH
    )
    assert foreign.status_code == 404
    assert client.post("/api/v1/incidents", json=body(scope)).status_code == 401
    assert (
        client.post("/api/v1/incidents", json=body(scope, extra=True), headers=AUTH).status_code
        == 422
    )
    assert incidents(session_factory) == []
