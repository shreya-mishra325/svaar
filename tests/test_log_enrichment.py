"""Attempt-bound hash provenance over real signed-ingress persistence and fake readers."""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from factories import make_org
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from test_incidents import deliver, run

from svaar.incidents.fingerprints import LogSignature
from svaar.incidents.models import ObservedEvent, WorkflowLogSignature
from svaar.integrations.github_app import GithubUnavailableError
from svaar.integrations.log_enrichment import enrich_event
from svaar.integrations.models import RepoMapping


@pytest.fixture
def observed(session_factory):
    with session_factory.begin() as session:
        org = make_org(session)
        session.add(RepoMapping(org_id=org.id, repository_id=101, installation_id=77))
        identifier = org.id
    assert deliver(session_factory, run()) == "accepted"
    with session_factory() as session:
        event = session.scalar(select(ObservedEvent))
        return identifier, event.id


def fake_reader(monkeypatch, sessions, *, digest="a" * 64, barrier=None, fail=False, remap=False):
    calls, closed = [], []

    class Reader:
        def workflow_attempt_signature(self, run_id, attempt, **expected):
            calls.append((run_id, attempt, expected))
            # No open DB transaction spans the provider request.
            assert sessions.kw["bind"].pool.checkedout() == 0
            if barrier:
                barrier.wait(timeout=5)
            if remap:
                with sessions.begin() as session:
                    session.get(RepoMapping, 101).installation_id = 88
            if fail:
                raise GithubUnavailableError("Synthetic reader unavailable")
            return LogSignature(digest, 1)

        def close(self):
            closed.append(True)

    def create(session, settings, org_id, repository_id):
        assert repository_id == 101
        mapping = session.get(RepoMapping, repository_id)
        assert mapping.org_id == org_id and mapping.installation_id == 77
        return Reader()

    monkeypatch.setattr("svaar.integrations.log_enrichment.GithubAppClient.for_repository", create)
    return calls, closed


def test_observation_to_durable_signature_is_idempotent(
    session_factory,
    settings,
    observed,
    monkeypatch,
):
    calls, closed = fake_reader(monkeypatch, session_factory)
    assert enrich_event(session_factory, settings, *observed) == "recorded"
    assert enrich_event(session_factory, settings, *observed) == "duplicate"
    assert len(calls) == len(closed) == 2
    assert calls[0] == (1001, 1, {"head_sha": "a" * 40, "workflow_id": 55, "branch": "main"})
    with session_factory() as session:
        signature = session.scalar(select(WorkflowLogSignature))
        assert signature.event_id == observed[1] and signature.org_id == observed[0]
        assert signature.run_attempt == 1 and signature.installation_id == 77
        assert signature.digest == "a" * 64 and len(signature.fingerprint) == 64
        assert session.scalar(select(func.count()).select_from(ObservedEvent)) == 1


def test_conflicting_digest_never_overwrites_first(
    session_factory, settings, observed, monkeypatch
):
    fake_reader(monkeypatch, session_factory)
    assert enrich_event(session_factory, settings, *observed) == "recorded"
    fake_reader(monkeypatch, session_factory, digest="b" * 64)
    assert enrich_event(session_factory, settings, *observed) == "conflict"
    with session_factory() as session:
        assert session.scalar(select(WorkflowLogSignature.digest)) == "a" * 64


def test_org_isolation_before_reader(session_factory, settings, observed, monkeypatch):
    calls, _ = fake_reader(monkeypatch, session_factory)
    assert enrich_event(session_factory, settings, uuid.uuid4(), observed[1]) == "not_found"
    assert not calls


@pytest.mark.parametrize("mode", ["unavailable", "remapped"])
def test_reader_failure_or_mapping_change_leaves_no_record(
    session_factory,
    settings,
    observed,
    monkeypatch,
    mode,
):
    _, closed = fake_reader(
        monkeypatch, session_factory, fail=mode == "unavailable", remap=mode == "remapped"
    )
    if mode == "unavailable":
        with pytest.raises(GithubUnavailableError):
            enrich_event(session_factory, settings, *observed)
    else:
        assert enrich_event(session_factory, settings, *observed) == "mapping_changed"
    assert closed == [True]
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(WorkflowLogSignature)) == 0


def test_concurrent_enrichment_records_one_hash(session_factory, settings, observed, monkeypatch):
    # Concurrency uses separate sessions and read-only provider calls; the write is serialized.
    barrier = threading.Barrier(2)

    class Reader:
        def workflow_attempt_signature(self, *args, **kwargs):
            barrier.wait(timeout=5)
            return LogSignature("a" * 64, 1)

        def close(self):
            pass

    monkeypatch.setattr(
        "svaar.integrations.log_enrichment.GithubAppClient.for_repository", lambda *args: Reader()
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: enrich_event(session_factory, settings, *observed), range(2))
        )
    assert sorted(results) == ["duplicate", "recorded"]
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(WorkflowLogSignature)) == 1


def test_attempts_are_separate_and_database_forbids_rewriting(
    session_factory,
    settings,
    observed,
    monkeypatch,
):
    fake_reader(monkeypatch, session_factory)
    assert enrich_event(session_factory, settings, *observed) == "recorded"
    assert deliver(session_factory, run(attempt=2)) == "accepted"
    with session_factory() as session:
        second = session.scalar(select(ObservedEvent).where(ObservedEvent.id != observed[1]))
        second_id = second.id
    assert enrich_event(session_factory, settings, observed[0], second_id) == "recorded"
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(WorkflowLogSignature)) == 2
        with pytest.raises(DBAPIError):
            session.execute(
                text("UPDATE workflow_log_signatures SET digest = :value"), {"value": "c" * 64}
            )
        session.rollback()
        with pytest.raises(DBAPIError):
            session.execute(text("DELETE FROM workflow_log_signatures"))
        session.rollback()


@pytest.mark.parametrize("mode", ["success", "requested", "missing_workflow"])
def test_ineligible_observations_never_fetch_logs(
    session_factory,
    settings,
    observed,
    monkeypatch,
    mode,
):
    calls, _ = fake_reader(monkeypatch, session_factory)
    body = run(
        run_id=1002,
        conclusion="success" if mode == "success" else "failure",
        action="requested" if mode == "requested" else "completed",
        workflow_id=None if mode == "missing_workflow" else 55,
    )
    assert deliver(session_factory, body) == "accepted"
    with session_factory() as session:
        event = next(
            row for row in session.scalars(select(ObservedEvent)) if row.data["run_id"] == 1002
        )
        identifier = event.id
    assert enrich_event(session_factory, settings, observed[0], identifier) == "unsupported"
    assert calls == []


def test_removed_mapping_never_fetches_logs(session_factory, settings, observed, monkeypatch):
    calls, _ = fake_reader(monkeypatch, session_factory)
    with session_factory.begin() as session:
        session.delete(session.get(RepoMapping, 101))
    assert enrich_event(session_factory, settings, *observed) == "unmapped"
    assert not calls
