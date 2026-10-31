"""Durable CI work over signed observations with mocked log readers, never live providers."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from factories import make_org
from sqlalchemy import func, select
from test_incidents import chat_route, incidents, outbox, run
from test_log_enrichment import fake_reader

from svaar.identity.models import Role
from svaar.incidents.models import IncidentEvent, ObservedEvent, WorkflowLogSignature
from svaar.integrations.github import ingest_delivery
from svaar.integrations.log_enrichment import enrich_event
from svaar.integrations.models import RepoMapping
from svaar.jobs.ci import CiWorker
from svaar.jobs.models import CiJob

pytestmark = pytest.mark.postgres


@pytest.fixture
def scope(session_factory):
    with session_factory.begin() as session:
        org = make_org(session)
        owner = chat_route(session, org, Role.DEV, "ci-owner")
        session.add(
            RepoMapping(
                repository_id=101, installation_id=77, org_id=org.id, owner_principal_id=owner
            )
        )
        return org.id, owner


def ingest(sessions, **kwargs):
    return ingest_delivery(
        sessions, uuid.uuid4(), "workflow_run", run(**kwargs), defer_grouping=True
    )


def worker(sessions, settings, now):
    return CiWorker(
        sessions, lambda org, event: enrich_event(sessions, settings, org, event), now=lambda: now
    )


def test_signed_ingress_defers_network_grouping_and_alerts(session_factory, scope):
    raw = run()
    receipt = uuid.uuid4()
    assert (
        ingest_delivery(session_factory, receipt, "workflow_run", raw, defer_grouping=True)
        == "accepted"
    )
    assert (
        ingest_delivery(session_factory, receipt, "workflow_run", raw, defer_grouping=True)
        == "duplicate"
    )
    assert incidents(session_factory) == [] and outbox(session_factory) == []
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(CiJob)) == 1


def test_repeat_signature_groups_one_incident_and_owner_alert(
    session_factory, scope, settings, monkeypatch
):
    ingest(session_factory)
    ingest(session_factory, run_id=1002)
    calls, closed = fake_reader(monkeypatch, session_factory)
    now = datetime.now(UTC) + timedelta(seconds=1)
    result = worker(session_factory, settings, now).run_once()
    assert result["done"] == 2
    [incident] = incidents(session_factory)
    assert incident.failure_count == 2 and incident.owner_principal_id == scope[1]
    assert len(outbox(session_factory)) == 1 and len(calls) == len(closed) == 2
    with session_factory() as session:
        signature = session.scalar(select(WorkflowLogSignature))
        assert signature.fingerprint == incident.fingerprint
    assert worker(session_factory, settings, now).run_once()["done"] == 0


def test_different_log_signatures_do_not_merge_failures(
    session_factory, scope, settings, monkeypatch
):
    ingest(session_factory)
    now = datetime.now(UTC) + timedelta(seconds=1)
    fake_reader(monkeypatch, session_factory, digest="a" * 64)
    assert worker(session_factory, settings, now).run_once()["done"] == 1
    ingest(session_factory, run_id=1002)
    fake_reader(monkeypatch, session_factory, digest="b" * 64)
    assert worker(session_factory, settings, now).run_once()["done"] == 1
    assert len(incidents(session_factory)) == len(outbox(session_factory)) == 2


def test_unavailable_logs_retry_then_fall_back_without_fake_signature(
    session_factory, scope, settings, monkeypatch
):
    ingest(session_factory)
    fake_reader(monkeypatch, session_factory, fail=True)
    now = datetime.now(UTC) + timedelta(seconds=1)
    assert worker(session_factory, settings, now).run_once()["pending"] == 1
    assert incidents(session_factory) == []
    assert worker(session_factory, settings, now + timedelta(seconds=61)).run_once()["pending"] == 1
    assert worker(session_factory, settings, now + timedelta(seconds=182)).run_once()["done"] == 1
    assert len(incidents(session_factory)) == len(outbox(session_factory)) == 1
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(WorkflowLogSignature)) == 0
        assert session.scalar(select(CiJob)).reason == "coarse_fallback"


def test_mapping_change_discards_job_without_alert(session_factory, scope, settings, monkeypatch):
    ingest(session_factory)
    fake_reader(monkeypatch, session_factory, remap=True)
    now = datetime.now(UTC) + timedelta(seconds=1)
    assert worker(session_factory, settings, now).run_once()["failed"] == 1
    assert incidents(session_factory) == [] and outbox(session_factory) == []


def test_expired_claim_reclaimed_and_old_worker_cannot_finalize(session_factory, scope):
    ingest(session_factory)
    now = datetime.now(UTC) + timedelta(seconds=1)
    instance = CiWorker(session_factory, lambda *_: "unsupported", now=lambda: now)
    first = instance._claim()
    assert first is not None
    assert instance._claim() is None
    instance.now = lambda: now + timedelta(minutes=6)
    second = instance._claim()
    assert second and second[0] == first[0] and second[1] != first[1]
    assert instance._finish(first[0], first[1], "logs_unavailable") == "superseded"
    assert instance._finish(second[0], second[1], "logs_unavailable") == "pending"


def test_concurrent_row_claim_has_one_winner(session_factory, scope):
    ingest(session_factory)
    now = datetime.now(UTC) + timedelta(seconds=1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: CiWorker(
                    session_factory, lambda *_: "unsupported", now=lambda: now
                )._claim(),
                range(2),
            )
        )
    assert sum(result is not None for result in results) == 1


def test_grouping_alert_failure_rolls_back_and_does_not_stop_other_job(
    session_factory, scope, settings, monkeypatch
):
    ingest(session_factory)
    ingest(session_factory, run_id=1002, workflow_id=56)
    now = datetime.now(UTC) + timedelta(seconds=1)
    fake_reader(monkeypatch, session_factory)
    from svaar.jobs import ci

    original = ci.queue_opened_alerts

    def queue(session, incident):
        if incident.workflow_id == 55:
            raise RuntimeError("synthetic outbox failure")
        return original(session, incident)

    monkeypatch.setattr(ci, "queue_opened_alerts", queue)
    result = worker(session_factory, settings, now).run_once()
    assert result["failed"] == 1 and result["done"] == 1
    [incident] = incidents(session_factory)
    assert incident.workflow_id == 56
    assert len(outbox(session_factory)) == 1
    monkeypatch.setattr(ci, "queue_opened_alerts", original)
    assert worker(session_factory, settings, now + timedelta(minutes=6)).run_once()["done"] == 1
    assert len(incidents(session_factory)) == len(outbox(session_factory)) == 2


def test_requested_before_failure_is_linked_without_changing_observations(
    session_factory, scope, settings, monkeypatch
):
    ingest(session_factory, action="in_progress", at="2026-10-23T09:59:00Z")
    ingest(session_factory)
    now = datetime.now(UTC) + timedelta(seconds=1)
    fake_reader(monkeypatch, session_factory)
    assert worker(session_factory, settings, now).run_once()["done"] == 2
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ObservedEvent)) == 2
        assert session.scalar(select(func.count()).select_from(IncidentEvent)) == 2


def test_later_success_joins_unique_incident_without_resolving_it(
    session_factory, scope, settings, monkeypatch
):
    ingest(session_factory)
    ingest(session_factory, run_id=1002, conclusion="success", at="2026-10-23T10:01:00Z")
    now = datetime.now(UTC) + timedelta(seconds=1)
    fake_reader(monkeypatch, session_factory)
    worker(session_factory, settings, now).run_once()
    worker(session_factory, settings, now + timedelta(seconds=61)).run_once()
    [incident] = incidents(session_factory)
    assert incident.state == "open" and incident.failure_count == 1
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(IncidentEvent)) == 2


@pytest.fixture
def dispatcher():
    from svaar.actions.catalog import build_registry
    from svaar.actions.dispatcher import ApprovalPolicy, Dispatcher

    return Dispatcher(build_registry(), ApprovalPolicy(timedelta(minutes=10), 3, False))


def call_ci(sessions, dispatcher, scope, name, arguments):
    from svaar.actions.registry import Channel, ToolContext

    with sessions.begin() as session:
        return dispatcher.dispatch(
            session, ToolContext(scope[0], scope[1], Channel.CHAT, None, "ci-read"), name, arguments
        )


def test_ci_read_tools_use_latest_observations_and_signature(
    session_factory, scope, settings, monkeypatch, dispatcher
):
    ingest(session_factory, action="in_progress", at="2026-10-23T09:59:00Z")
    ingest(session_factory)
    fake_reader(monkeypatch, session_factory)
    worker(session_factory, settings, datetime.now(UTC) + timedelta(seconds=1)).run_once()
    runs = call_ci(session_factory, dispatcher, scope, "list_ci_runs", {"repository_id": 101})
    assert len(runs.output["runs"]) == 1
    assert runs.output["runs"][0]["status"] == "completed" and not runs.output["live_refresh"]
    failure = call_ci(
        session_factory,
        dispatcher,
        scope,
        "explain_ci_failure",
        {"repository_id": 101, "run_id": 1001, "run_attempt": 1},
    )
    assert failure.output["found"] and failure.output["failed"]
    assert failure.output["log_signature"]["algorithm"] == "log-tail-v1"
    assert failure.output["category"] == "unknown" and not failure.output["cause_established"]


def test_ci_read_tools_do_not_leak_foreign_repository(session_factory, scope, dispatcher):
    from factories import make_principal

    with session_factory.begin() as session:
        other = make_org(session)
        principal = make_principal(session, other, Role.DEV)
        foreign = other.id, principal.id
    ingest(session_factory)
    runs = call_ci(session_factory, dispatcher, foreign, "list_ci_runs", {"repository_id": 101})
    assert runs.output["runs"] == []
    failure = call_ci(
        session_factory,
        dispatcher,
        foreign,
        "explain_ci_failure",
        {"repository_id": 101, "run_id": 1001, "run_attempt": 1},
    )
    assert failure.output == {"found": False}


def test_ci_webhook_flag_enqueues_job_without_provider_access(
    database_url, session_factory, scope, monkeypatch
):
    import hashlib
    import hmac

    from fastapi.testclient import TestClient

    from svaar.app import create_app
    from svaar.config import Settings

    secret = "w" * 32
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        github_webhook_secret=secret,
        github_enrichment_enabled=True,
    )
    monkeypatch.setattr(
        "svaar.integrations.log_enrichment.GithubAppClient.for_repository",
        lambda *_args, **_kwargs: pytest.fail("provider constructed in webhook"),
    )
    payload = run()
    headers = {
        "X-Hub-Signature-256": "sha256="
        + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest(),
        "X-GitHub-Delivery": str(uuid.uuid4()),
        "X-GitHub-Event": "workflow_run",
    }
    with TestClient(create_app(settings)) as client:
        assert (
            client.post("/api/v1/webhooks/github", content=payload, headers=headers).status_code
            == 200
        )
    assert incidents(session_factory) == []
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(CiJob)) == 1


def test_ci_cli_disabled_without_provider_or_database_work(settings, monkeypatch):
    from svaar.jobs import __main__ as cli

    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr(cli, "create_database_engine", lambda *_: pytest.fail("database work"))
    assert cli.main(["--once"]) == 2
