"""Signed merge observations support only exact, scoped fix_merged claims."""

import json
import uuid

import pytest
from factories import make_org, make_principal
from pydantic import ValidationError
from sqlalchemy import func, select
from test_incidents import deliver, incidents, run

from svaar.incidents.claims import ClaimInput, check_claim, record_claim
from svaar.incidents.models import Claim, ClaimEvidence, Incident, ObservedEvent
from svaar.integrations.github import GithubPayloadError, ingest_delivery
from svaar.integrations.models import RepoMapping
from svaar.jobs.models import CiJob

pytestmark = pytest.mark.postgres


def merge(number=42, merged=True, at="2026-10-23T11:00:00Z", repository=101, **changes):
    pull = {
        "number": number,
        "merged": merged,
        "merged_at": at if merged else None,
        "merge_commit_sha": "c" * 40 if merged else None,
        "head": {"sha": "b" * 40, "ref": "fix/deploy"},
        "base": {"sha": "a" * 40, "ref": "main"},
    }
    pull.update(changes)
    return json.dumps(
        {
            "action": "closed",
            "repository": {"id": repository},
            "installation": {"id": 77},
            "pull_request": pull,
        }
    ).encode()


def deliver_merge(sessions, raw, delivery=None):
    return ingest_delivery(sessions, delivery or uuid.uuid4(), "pull_request", raw)


@pytest.fixture
def scope(session_factory):
    with session_factory.begin() as session:
        org = make_org(session)
        author = make_principal(session, org)
        session.add(RepoMapping(repository_id=101, installation_id=77, org_id=org.id))
        session.add(RepoMapping(repository_id=202, installation_id=77, org_id=org.id))
        ids = org.id, author.id
    deliver(session_factory, run(at="2026-10-23T10:00:00Z"))
    [incident] = incidents(session_factory)
    return (*ids, incident.id)


def claim(sessions, scope, statement="The fix is merged.", pull_number=42, source="m-1"):
    with sessions.begin() as session:
        row = record_claim(
            session,
            scope[0],
            scope[1],
            ClaimInput(
                incident_id=scope[2],
                statement=statement,
                kind="fix_merged",
                pull_number=pull_number,
            ),
            source,
        )
        return row.id, row.status


def test_merged_pull_request_is_an_observation_that_never_opens_incidents(session_factory, scope):
    delivery = uuid.uuid4()
    assert deliver_merge(session_factory, merge(), delivery) == "accepted"
    assert deliver_merge(session_factory, merge(), delivery) == "duplicate"
    assert deliver_merge(session_factory, merge()) == "accepted"  # same fact, new delivery ID
    with session_factory() as session:
        [event] = session.scalars(
            select(ObservedEvent).where(ObservedEvent.kind == "pull_request.merged")
        ).all()
        assert event.data["pull_number"] == 42 and event.data["merge_commit_sha"] == "c" * 40
        assert session.scalar(select(func.count()).select_from(Incident)) == 1
        assert session.scalar(select(func.count()).select_from(CiJob)) == 0


def test_unmerged_close_is_ignored_and_merge_without_provenance_is_rejected(session_factory, scope):
    assert deliver_merge(session_factory, merge(merged=False)) == "ignored"
    with pytest.raises(GithubPayloadError):
        deliver_merge(session_factory, merge(merge_commit_sha=None))
    assert deliver_merge(session_factory, merge(repository=999)) == "unmapped"


def test_exact_merge_after_the_incident_confirms_with_provenance(session_factory, scope):
    identifier, status = claim(session_factory, scope)
    assert status == "unverified"
    deliver_merge(session_factory, merge())
    with session_factory.begin() as session:
        assert check_claim(session, scope[0], identifier).status == "confirmed"
        assert check_claim(session, scope[0], identifier).status == "confirmed"
    with session_factory() as session:
        [evidence] = session.scalars(select(ClaimEvidence)).all()
        assert (evidence.stance, evidence.rule) == ("supports", "merge-event-v1")
        assert evidence.claim_answer_id is None


@pytest.mark.parametrize(
    ("raw", "changes"),
    [
        (merge(number=7), {}),
        (merge(at="2026-10-23T09:00:00Z"), {}),
        (merge(repository=202), {}),
        (merge(), {"pull_number": None}),
        (merge(), {"statement": "PR 7 was merged."}),
        (merge(), {"statement": "Is the fix merged?"}),
        (merge(), {"statement": "The fix is not merged."}),
        (merge(), {"statement": "The fix is merged and the build passed."}),
    ],
)
def test_missing_or_mismatched_merges_leave_claims_unverified(session_factory, scope, raw, changes):
    deliver_merge(session_factory, raw)
    assert claim(session_factory, scope, **changes)[1] == "unverified"
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ClaimEvidence)) == 0


def test_named_pull_request_must_match_target(session_factory, scope):
    deliver_merge(session_factory, merge())
    assert claim(session_factory, scope, statement="PR #42 was merged.")[1] == "confirmed"


def test_merge_in_another_organization_is_never_evidence(session_factory, scope):
    with session_factory.begin() as session:
        session.get(RepoMapping, 101).org_id = make_org(session).id
    deliver_merge(session_factory, merge())
    assert claim(session_factory, scope)[1] == "unverified"
    with session_factory() as session:
        assert session.get(Claim, claim(session_factory, scope)[0]).status == "unverified"


def test_workflow_claims_cannot_target_pull_requests():
    with pytest.raises(ValidationError):
        ClaimInput(
            incident_id=uuid.uuid4(),
            statement="The build passed.",
            kind="workflow_succeeded",
            run_id=1,
            run_attempt=1,
            pull_number=42,
        )
