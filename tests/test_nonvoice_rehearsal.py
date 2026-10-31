"""Rehearse the non-voice incident path with fake logs and a simulated confirmation."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from test_ci_jobs import ingest
from test_ci_jobs import scope as scope
from test_incidents import incidents, outbox
from test_log_enrichment import fake_reader
from test_resolution_api import DEMO
from test_resolution_validator import BASE

from svaar.actions.catalog import build_registry
from svaar.actions.dispatcher import ApprovalPolicy, Dispatcher
from svaar.actions.missions import Mission
from svaar.actions.models import ToolStatus
from svaar.actions.registry import Channel, ToolContext
from svaar.identity.models import Principal, Role
from svaar.incidents.models import Claim, ObservedEvent
from svaar.integrations.log_enrichment import enrich_event
from svaar.jobs.ci import CiWorker
from svaar.resolution import policy
from svaar.resolution.models import ExceptionDraft


def test_nonvoice_incident_resolution_rehearsal(session_factory, scope, settings, monkeypatch):
    """No live transport, LLM or provider mutation is needed for this scenario."""
    ingest(session_factory)
    fake_reader(monkeypatch, session_factory)
    clock = datetime.now(UTC) + timedelta(seconds=1)
    worker = CiWorker(
        session_factory,
        lambda org, event: enrich_event(session_factory, settings, org, event),
        now=lambda: clock,
    )
    assert worker.run_once()["done"] == 1
    [incident] = incidents(session_factory)
    assert len(outbox(session_factory)) == 1
    with session_factory.begin() as session:
        session.get(Principal, scope[1]).role = Role.LEAD
        policy.replace_constraints(session, scope[0], BASE, expected_revision=0)
    gate = Dispatcher(build_registry(), ApprovalPolicy(timedelta(minutes=10), 3, False))

    def dispatch(name, args, *, voice=False):
        context = ToolContext(
            scope[0],
            scope[1],
            Channel.VOICE if voice else Channel.CHAT,
            Mission.CONFIRMATION if voice else None,
            f"rehearsal:{name}",
        )
        with session_factory() as session:
            result = gate.dispatch(session, context, name, args)
            session.commit()
            assert result.status in {ToolStatus.SUCCEEDED, ToolStatus.CONFIRMATION_REQUIRED}
            return result

    timeline = dispatch("get_timeline", {"incident_id": str(incident.id)})
    assert timeline.output["events"][0]["conclusion"] == "failure"
    assert dispatch("acknowledge_incident", {"incident_id": str(incident.id)}).output[
        "acknowledged"
    ]
    ingest(session_factory, run_id=1002, conclusion="success", at="2026-10-23T10:01:00Z")
    worker.run_once()
    assertion = dispatch(
        "record_claim",
        {
            "incident_id": str(incident.id),
            "statement": "workflow succeeded",
            "kind": "workflow_succeeded",
            "run_id": 1002,
            "run_attempt": 1,
        },
    )
    with session_factory() as session:
        claim = session.scalar(select(Claim))
        claim_id = claim.id
    assert assertion.output
    checked = dispatch("check_claim", {"claim_id": str(claim_id)})
    assert checked.output["claim"]["status"] == "confirmed"
    negotiation = dispatch(
        "start_negotiation",
        {"incident_id": str(incident.id), "proposal": DEMO.model_dump(mode="json")},
    )
    assert [row["valid"] for row in negotiation.output["rounds"]] == [False, True]
    with session_factory() as session:
        observed_before = session.scalar(select(func.count()).select_from(ObservedEvent))
    replay = dispatch(
        "request_replay",
        {
            "incident_id": str(incident.id),
            "negotiation_id": negotiation.output["negotiation_id"],
            "scenario": {"steps": [{"name": "test", "recorded": "failure"}], "fixes": ["test"]},
        },
    )
    assert replay.output["kind"] == "simulated"
    pending = dispatch("approve_exception", {"draft_id": negotiation.output["draft_id"]})
    assert pending.status == ToolStatus.CONFIRMATION_REQUIRED and pending.ticket
    confirmed = dispatch("confirm_action", {"code": pending.ticket.nonce}, voice=True)
    assert confirmed.output["result"]["approved"]
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ObservedEvent)) == observed_before
        assert (
            session.get(ExceptionDraft, uuid.UUID(negotiation.output["draft_id"])).state
            == "approved"
        )
