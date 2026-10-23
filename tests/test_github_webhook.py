"""Synthetic signed GitHub deliveries, real PostgreSQL, no GitHub API calls."""

import hashlib
import hmac
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from factories import make_org
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, func, select, update
from sqlalchemy.exc import DBAPIError

from svaar.app import create_app
from svaar.config import Settings
from svaar.incidents.models import ObservedEvent
from svaar.integrations.github import ingest_delivery
from svaar.integrations.models import RepoMapping, WebhookDelivery

SECRET = "g" * 32
OPERATOR = "o" * 32


@pytest.fixture
def web_client(session_factory, database_url):
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        environment="test",
        github_webhook_secret=SECRET,
        operator_token=OPERATOR,
    )
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def mapped_org(session_factory):
    with session_factory.begin() as session:
        org = make_org(session)
        session.add(RepoMapping(repository_id=101, installation_id=77, org_id=org.id))
        return org.id


def payload():
    return {
        "action": "completed",
        "repository": {"id": 101},
        "installation": {"id": 77},
        "workflow_run": {
            "id": 1001,
            "run_attempt": 1,
            "head_sha": "a" * 40,
            "status": "completed",
            "conclusion": "failure",
            "updated_at": "2026-10-23T10:00:00Z",
        },
        "sender": {"email": "private-person@example.invalid", "name": "private-person"},
    }


def encode(body):
    return json.dumps(body, ensure_ascii=False).encode()


def headers(raw, delivery=None, kind="workflow_run"):
    return {
        "X-Hub-Signature-256": "sha256="
        + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest(),
        "X-GitHub-Delivery": str(delivery or uuid.uuid4()),
        "X-GitHub-Event": kind,
        "Content-Type": "application/json",
    }


def post(client, body=None, delivery=None, kind="workflow_run"):
    raw = encode(payload() if body is None else body)
    return client.post("/api/v1/webhooks/github", content=raw, headers=headers(raw, delivery, kind))


def count(sessions, model):
    with sessions() as session:
        return session.scalar(select(func.count()).select_from(model))


def test_valid_delivery_normalizes_and_deduplicates(web_client, mapped_org, session_factory):
    delivery = uuid.uuid4()
    assert post(web_client, delivery=delivery).json() == {"handled": True, "status": "accepted"}
    assert post(web_client, delivery=delivery).json() == {"handled": True, "status": "duplicate"}
    assert count(session_factory, ObservedEvent) == count(session_factory, WebhookDelivery) == 1
    with session_factory() as session:
        observed = session.scalar(select(ObservedEvent))
        assert observed.org_id == mapped_org and observed.source_delivery_id == delivery
        assert observed.data["run_id"] == 1001 and observed.data["conclusion"] == "failure"
        assert "private-person" not in str(observed.data)


def test_same_transition_new_delivery_keeps_one_observation(
    web_client, mapped_org, session_factory
):
    assert post(web_client).status_code == 200
    assert post(web_client).status_code == 200
    assert count(session_factory, ObservedEvent) == 1
    assert count(session_factory, WebhookDelivery) == 2


def test_changed_delivery_or_event_contents_conflict(web_client, mapped_org, session_factory):
    identifier = uuid.uuid4()
    post(web_client, delivery=identifier)
    changed = payload()
    changed["workflow_run"]["conclusion"] = "success"
    assert post(web_client, changed, delivery=identifier).status_code == 409
    assert post(web_client, changed).status_code == 409
    assert count(session_factory, ObservedEvent) == count(session_factory, WebhookDelivery) == 1


@pytest.mark.parametrize("signature", [None, "bad", "sha256=" + "0" * 64, "sha256=" + "é" * 64])
def test_bad_signature_never_persists(web_client, session_factory, signature):
    raw = encode(payload())
    hdrs = headers(raw)
    if signature is None:
        del hdrs["X-Hub-Signature-256"]
    else:
        hdrs["X-Hub-Signature-256"] = signature
    # HTTP headers must be ASCII; test malformed Unicode via a percent-encoded value.
    if signature and "é" in signature:
        hdrs["X-Hub-Signature-256"] = "sha256=%C3%A9"
    response = web_client.post("/api/v1/webhooks/github", content=raw, headers=hdrs)
    assert response.status_code == 401
    assert count(session_factory, WebhookDelivery) == 0


def test_raw_bytes_are_authenticated_before_json(web_client, session_factory):
    raw = encode(payload())
    assert (
        web_client.post(
            "/api/v1/webhooks/github", content=raw + b" ", headers=headers(raw)
        ).status_code
        == 401
    )
    malformed = b'{"action":"completed","action":"requested"}'
    assert (
        web_client.post(
            "/api/v1/webhooks/github", content=malformed, headers=headers(malformed)
        ).status_code
        == 400
    )
    assert count(session_factory, WebhookDelivery) == 0


@pytest.mark.parametrize(
    "change", ["bool_repo", "no_installation", "naive_time", "conclusion", "mismatch", "bad_sha"]
)
def test_malformed_workflow_is_rejected_without_leaking_body(web_client, session_factory, change):
    body = payload()
    if change == "bool_repo":
        body["repository"]["id"] = True
    elif change == "no_installation":
        del body["installation"]
    elif change == "naive_time":
        body["workflow_run"]["updated_at"] = "2026-10-23T10:00:00"
    elif change == "conclusion":
        body["workflow_run"]["conclusion"] = "made-up"
    elif change == "mismatch":
        body["workflow_run"]["status"] = "in_progress"
    else:
        body["workflow_run"]["head_sha"] = "private-invalid"
    response = post(web_client, body)
    assert response.status_code == 422 and "private" not in response.text
    assert count(session_factory, WebhookDelivery) == 0


@pytest.mark.parametrize("change", ["repository", "installation", "event"])
def test_unmapped_or_unsupported_deliveries_have_no_observation(
    web_client, mapped_org, session_factory, change
):
    body = payload()
    kind = "workflow_run"
    if change == "repository":
        body["repository"]["id"] = 999
    elif change == "installation":
        body["installation"]["id"] = 999
    else:
        kind = "push"
    response = post(web_client, body, kind=kind)
    if change == "event":
        assert response.status_code == 200 and response.json() == {"handled": False}
    else:
        assert response.status_code == 404
    assert count(session_factory, ObservedEvent) == 0
    assert count(session_factory, WebhookDelivery) == 1


def test_independent_events_keep_source_order_time(web_client, mapped_org, session_factory):
    later = payload()
    later["workflow_run"]["updated_at"] = "2026-10-23T10:01:00Z"
    assert post(web_client, later).status_code == 200
    assert post(web_client).status_code == 200
    with session_factory() as session:
        events = list(session.scalars(select(ObservedEvent).order_by(ObservedEvent.occurred_at)))
        assert len(events) == 2 and events[0].occurred_at < events[1].occurred_at


def test_concurrent_deliveries_create_one_effect(mapped_org, session_factory):
    raw, identifier = encode(payload()), uuid.uuid4()
    barrier = threading.Barrier(3)

    def ingest(_):
        barrier.wait()
        return ingest_delivery(session_factory, identifier, "workflow_run", raw)

    with ThreadPoolExecutor(max_workers=3) as pool:
        assert sorted(pool.map(ingest, range(3))) == ["accepted", "duplicate", "duplicate"]
    assert count(session_factory, ObservedEvent) == 1


def test_receipt_failure_rolls_back_observation(web_client, mapped_org, session_factory):
    def fail(*args):
        raise RuntimeError("private-provider-data")

    event.listen(WebhookDelivery, "before_insert", fail)
    try:
        response = post(web_client)
        assert response.status_code == 500 and "private" not in response.text
    finally:
        event.remove(WebhookDelivery, "before_insert", fail)
    assert count(session_factory, ObservedEvent) == count(session_factory, WebhookDelivery) == 0


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_observations_are_append_only(web_client, mapped_org, session_factory, operation):
    post(web_client)
    with session_factory() as session:
        statement = (
            update(ObservedEvent).values(kind="tampered")
            if operation == "update"
            else delete(ObservedEvent)
        )
        with pytest.raises(DBAPIError):
            session.execute(statement)
        session.rollback()
    assert count(session_factory, ObservedEvent) == 1


def test_body_limit_applies_before_database_work(web_client, session_factory):
    raw = b"x" * (1024 * 1024 + 1)
    assert (
        web_client.post("/api/v1/webhooks/github", content=raw, headers=headers(raw)).status_code
        == 413
    )
    assert count(session_factory, WebhookDelivery) == 0


def test_explicit_mapping_is_operator_only_and_cannot_be_overwritten(web_client, session_factory):
    with session_factory.begin() as session:
        org = make_org(session)
        org_id = org.id
    body = {"repository_id": 101, "installation_id": 77, "org_id": str(org_id)}
    assert web_client.post("/api/v1/repo-mappings", json=body).status_code == 401
    assert (
        web_client.post(
            "/api/v1/repo-mappings", json=body, headers={"Authorization": "Bearer " + SECRET}
        ).status_code
        == 401
    )
    hdrs = {"Authorization": "Bearer " + OPERATOR}
    assert web_client.post("/api/v1/repo-mappings", json=body, headers=hdrs).status_code == 201
    assert web_client.post("/api/v1/repo-mappings", json=body, headers=hdrs).status_code == 409
    body["repository_id"], body["org_id"] = 102, str(uuid.uuid4())
    assert web_client.post("/api/v1/repo-mappings", json=body, headers=hdrs).status_code == 404


def test_missing_secret_disables_ingress_without_database(settings):
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        assert post(client).status_code == 503


def test_webhook_secret_is_optional_hidden_and_validated(settings):
    assert settings.github_webhook_secret is None
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url=settings.database_url,
            github_webhook_secret="short-private",
        )
    configured = Settings(
        _env_file=None, database_url=settings.database_url, github_webhook_secret=SECRET
    )
    assert SECRET not in repr(configured) and SECRET not in configured.model_dump_json()


def test_unsupported_and_unmapped_redelivery_preserves_original_outcome(
    web_client,
    session_factory,
):
    identifier = uuid.uuid4()
    assert post(web_client, delivery=identifier).status_code == 404
    assert post(web_client, delivery=identifier).status_code == 404
    unsupported = uuid.uuid4()
    assert post(web_client, delivery=unsupported, kind="push").json() == {"handled": False}
    assert post(web_client, delivery=unsupported, kind="push").json() == {"handled": False}
    assert count(session_factory, WebhookDelivery) == 2
    assert count(session_factory, ObservedEvent) == 0
