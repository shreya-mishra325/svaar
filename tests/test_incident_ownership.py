"""Explicit operator ownership and owner-only outbox alerts; no live delivery."""

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from factories import make_org
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_incidents import chat_route, deliver, incidents, outbox, run

from svaar.app import create_app
from svaar.config import Settings
from svaar.identity.models import Org, Role
from svaar.incidents import service
from svaar.incidents.models import Incident
from svaar.integrations.models import RepoMapping

TOKEN = "o" * 32
AUTH = {"Authorization": "Bearer " + TOKEN}


@pytest.fixture
def scope(session_factory):
    with session_factory.begin() as session:
        org = make_org(session)
        owner = chat_route(session, org, Role.DEV, "owner")
        other = chat_route(session, org, Role.LEAD, "other")
        foreign = chat_route(session, make_org(session), Role.ADMIN, "foreign")
        session.add(RepoMapping(repository_id=101, installation_id=77, org_id=org.id))
        return org.id, owner, other, foreign


@pytest.fixture
def client(database_url):
    settings = Settings(_env_file=None, database_url=database_url, operator_token=TOKEN)
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        yield client


def assign(client, scope, **extra):
    return client.put(
        "/api/v1/repo-mappings/101/owner",
        headers=AUTH,
        json={
            "org_id": str(scope[0]),
            "owner_principal_id": str(scope[1]),
            **extra,
        },
    )


def test_only_configured_owner_gets_alert_even_when_dev(session_factory, scope, client):
    assert assign(client, scope).status_code == 200
    assert deliver(session_factory, run()) == "accepted"
    [incident] = incidents(session_factory)
    assert incident.owner_principal_id == scope[1]
    [message] = outbox(session_factory)
    assert message.notification_key == f"incident-opened:{incident.id}:{scope[1]}"
    assert deliver(session_factory, run(run_id=1002)) == "accepted"
    assert len(outbox(session_factory)) == 1


def test_no_owner_never_broadcasts_to_other_leads(session_factory, scope):
    assert deliver(session_factory, run()) == "accepted"
    assert outbox(session_factory) == []
    assert incidents(session_factory)[0].owner_principal_id is None


def test_owner_endpoint_requires_operator_and_same_org(session_factory, scope, client):
    body = {"org_id": str(scope[0]), "owner_principal_id": str(scope[1])}
    assert client.put("/api/v1/repo-mappings/101/owner", json=body).status_code == 401
    assert assign(client, scope, owner_principal_id=str(scope[3])).status_code == 404
    assert assign(client, scope, org_id=str(uuid.uuid4())).status_code == 404
    with session_factory() as session:
        assert session.get(RepoMapping, 101).owner_principal_id is None


def test_create_mapping_rejects_foreign_owner(scope, client):
    response = client.post(
        "/api/v1/repo-mappings",
        headers=AUTH,
        json={
            "repository_id": 102,
            "installation_id": 77,
            "org_id": str(scope[0]),
            "owner_principal_id": str(scope[3]),
        },
    )
    assert response.status_code == 404


def test_create_mapping_accepts_explicit_owner(scope, client):
    response = client.post(
        "/api/v1/repo-mappings",
        headers=AUTH,
        json={
            "repository_id": 102,
            "installation_id": 77,
            "org_id": str(scope[0]),
            "owner_principal_id": str(scope[1]),
        },
    )
    assert response.status_code == 201
    assert response.json()["owner_principal_id"] == str(scope[1])


def test_assigning_future_owner_does_not_silently_backfill(session_factory, scope, client):
    deliver(session_factory, run())
    assert assign(client, scope).json()["assigned_incidents"] == 0
    assert incidents(session_factory)[0].owner_principal_id is None
    assert outbox(session_factory) == []
    deliver(session_factory, run(run_id=1002, branch="other"))
    with session_factory() as session:
        fresh = session.scalar(select(Incident).where(Incident.head_branch == "other"))
        assert fresh.owner_principal_id == scope[1]


def test_explicit_assignment_is_idempotent_and_queues_once(session_factory, scope, client):
    deliver(session_factory, run())
    assert assign(client, scope, assign_unowned_incidents=True).json()["assigned_incidents"] == 1
    assert assign(client, scope, assign_unowned_incidents=True).json()["assigned_incidents"] == 0
    assert len(outbox(session_factory)) == 1
    assert incidents(session_factory)[0].owner_principal_id == scope[1]


def test_mapping_owner_change_never_transfers_existing_incident(session_factory, scope, client):
    assign(client, scope)
    deliver(session_factory, run())
    response = assign(
        client, scope, owner_principal_id=str(scope[2]), assign_unowned_incidents=True
    )
    assert response.status_code == 200 and response.json()["assigned_incidents"] == 0
    assert incidents(session_factory)[0].owner_principal_id == scope[1]
    assert len(outbox(session_factory)) == 1


def test_acknowledged_incident_is_not_assigned_retroactively(session_factory, scope, client):
    deliver(session_factory, run())
    [incident] = incidents(session_factory)
    with session_factory.begin() as session:
        service.acknowledge(session, scope[0], incident.id, scope[2])
    assert assign(client, scope, assign_unowned_incidents=True).json()["assigned_incidents"] == 0
    assert incidents(session_factory)[0].owner_principal_id is None
    assert outbox(session_factory) == []


def test_alert_failure_rolls_back_mapping_and_incident_assignment(
    session_factory,
    scope,
    client,
    monkeypatch,
):
    deliver(session_factory, run())

    def fail(*args):
        raise RuntimeError("synthetic-outbox-error")

    monkeypatch.setattr("svaar.integrations.routes.queue_opened_alerts", fail)
    assert assign(client, scope, assign_unowned_incidents=True).status_code == 500
    with session_factory() as session:
        assert session.get(RepoMapping, 101).owner_principal_id is None
        assert session.scalar(select(Incident.owner_principal_id)) is None
    assert outbox(session_factory) == []


def test_concurrent_assignment_queues_one_owner_alert(session_factory, scope, client):
    deliver(session_factory, run())
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(
                lambda _: assign(client, scope, assign_unowned_incidents=True),
                range(2),
            )
        )
    assert all(response.status_code == 200 for response in responses)
    assert sorted(response.json()["assigned_incidents"] for response in responses) == [0, 1]
    assert len(outbox(session_factory)) == 1


def test_foreign_owner_in_mapping_never_receives_incident_alert(session_factory, scope):
    # Defense in depth if a mapping was populated outside the operator route.
    with session_factory.begin() as session:
        session.get(RepoMapping, 101).owner_principal_id = scope[3]
    deliver(session_factory, run())
    assert incidents(session_factory)[0].owner_principal_id is None
    assert outbox(session_factory) == []


def test_owner_without_private_route_is_not_replaced_by_a_lead(session_factory, scope, client):
    from factories import make_principal

    with session_factory.begin() as session:
        person = make_principal(session, session.get(Org, scope[0]), Role.DEV)
        identifier = person.id
    assert assign(client, scope, owner_principal_id=str(identifier)).status_code == 200
    deliver(session_factory, run())
    assert incidents(session_factory)[0].owner_principal_id == identifier
    assert outbox(session_factory) == []


def test_downgrade_refuses_to_discard_assigned_owners(session_factory, scope, client):
    import importlib.util

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy.exc import DBAPIError

    assert assign(client, scope).status_code == 200
    spec = importlib.util.spec_from_file_location(
        "ownership_migration",
        "migrations/versions/0016_explicit_incident_ownership.py",
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with session_factory() as session:
        with Operations.context(MigrationContext.configure(session.connection())):
            with pytest.raises(DBAPIError, match="Reconcile assigned ownership"):
                migration.downgrade()
        session.rollback()
        assert session.get(RepoMapping, 101).owner_principal_id == scope[1]
