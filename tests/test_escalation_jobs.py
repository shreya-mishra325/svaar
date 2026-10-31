"""Escalation preparation uses confirmed delivery, scoped owners and local intents."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from factories import make_org
from sqlalchemy import select
from test_incidents import chat_route, deliver, incidents, run

from svaar.agent.models import OutboxMessage
from svaar.agent.notifications import delivered_incident_alert_at
from svaar.identity.models import ChannelBinding, Role
from svaar.incidents.models import Incident
from svaar.integrations.models import RepoMapping
from svaar.jobs.escalation import EscalationWorker
from svaar.jobs.models import EscalationJob
from svaar.voice.calls import prepare_escalation_call
from svaar.voice.models import VoiceCall

pytestmark = pytest.mark.postgres
NOW = datetime.now(UTC)


def escalation_scope(session_factory):
    """An owned open incident whose owner alert was delivered just over the grace ago."""
    with session_factory.begin() as session:
        org = make_org(session)
        owner = chat_route(session, org, Role.DEV, "escalation-owner")
        session.add(
            ChannelBinding(
                principal_id=owner, channel="phone", address="+15555550123", verified_at=NOW
            )
        )
        session.add(
            RepoMapping(
                repository_id=101, installation_id=77, org_id=org.id, owner_principal_id=owner
            )
        )
    assert deliver(session_factory, run()) == "accepted"
    [incident] = incidents(session_factory)
    with session_factory.begin() as session:
        message = session.scalar(select(OutboxMessage))
        message.state = "sent"
        message.sent_at = NOW - timedelta(seconds=601)
    return org.id, owner, incident.id


@pytest.fixture
def scope(session_factory):
    return escalation_scope(session_factory)


def worker(sessions, **kwargs):
    return EscalationWorker(
        sessions,
        delivered_alert_at=delivered_incident_alert_at,
        prepare_call=prepare_escalation_call,
        now=lambda: NOW,
        **kwargs,
    )


def calls(sessions):
    with sessions() as session:
        return list(session.scalars(select(VoiceCall)))


def test_concurrent_workers_prepare_one_intent(session_factory, scope):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker(session_factory).run_once(), range(2)))
    assert sum(result["prepared"] for result in results) == 1
    [call] = calls(session_factory)
    assert call.incident_id == scope[2]
    assert call.principal_id == scope[1]
    assert call.state == "pending"
    assert worker(session_factory).run_once()["prepared"] == 0


@pytest.mark.parametrize("state", ["pending", "unknown"])
def test_unconfirmed_delivery_does_not_prepare(session_factory, scope, state):
    with session_factory.begin() as session:
        session.scalar(select(OutboxMessage)).state = state
    assert worker(session_factory).run_once()["deferred"] == 1
    assert calls(session_factory) == []


def test_delivery_starts_grace(session_factory, scope):
    with session_factory.begin() as session:
        session.scalar(select(OutboxMessage)).sent_at = NOW
    assert worker(session_factory).run_once()["deferred"] == 1
    assert calls(session_factory) == []
    with session_factory() as session:
        assert session.scalar(select(EscalationJob)).next_check_at == NOW + timedelta(seconds=600)


def test_acknowledged_before_retry_cancels(session_factory, scope):
    with session_factory.begin() as session:
        session.scalar(select(OutboxMessage)).state = "pending"
    worker(session_factory).run_once()
    with session_factory.begin() as session:
        session.get(Incident, scope[2]).state = "acknowledged"
    instance = worker(session_factory)
    instance.now = lambda: NOW + timedelta(seconds=61)
    assert instance.run_once()["canceled"] == 1
    assert calls(session_factory) == []


def test_unverified_phone_can_be_verified_then_retried(session_factory, scope):
    with session_factory.begin() as session:
        phone = session.scalar(select(ChannelBinding).where(ChannelBinding.channel == "phone"))
        phone.verified_at = None
    assert worker(session_factory).run_once()["deferred"] == 1
    assert calls(session_factory) == []
    with session_factory.begin() as session:
        session.scalar(
            select(ChannelBinding).where(ChannelBinding.channel == "phone")
        ).verified_at = NOW
    instance = worker(session_factory)
    instance.now = lambda: NOW + timedelta(seconds=61)
    assert instance.run_once()["prepared"] == 1


def test_recipient_cooldown_between_incidents(session_factory, scope):
    assert deliver(session_factory, run(run_id=1002, workflow_id=56)) == "accepted"
    with session_factory.begin() as session:
        for message in session.scalars(select(OutboxMessage)):
            message.state, message.sent_at = "sent", NOW - timedelta(seconds=601)
    result = worker(session_factory).run_once()
    assert result["prepared"] == 1
    assert result["deferred"] == 1
    assert len(calls(session_factory)) == 1


def test_partial_preparation_failure_rolls_back_intent(session_factory, scope):
    instance = worker(session_factory)

    def fail(session, org, owner, incident):
        prepare_escalation_call(session, org, owner, incident)
        raise RuntimeError("simulated")

    instance.prepare_call = fail
    assert instance.run_once()["failed"] == 1
    assert calls(session_factory) == []
    instance.prepare_call = prepare_escalation_call
    instance.now = lambda: NOW + timedelta(seconds=61)
    assert instance.run_once()["prepared"] == 1


def test_prepared_intent_cannot_dial_without_explicit_guard(session_factory, scope):
    from unittest.mock import Mock

    from svaar.voice.calls import CallService

    worker(session_factory).run_once()
    [call] = calls(session_factory)
    provider = Mock()
    assert CallService(session_factory, provider).place(scope[0], call.id) == "not_authorized"
    provider.place_call.assert_not_called()


@pytest.mark.parametrize("tool", ["get_timeline", "list_claims", "acknowledge_incident"])
def test_voice_tools_cannot_select_another_incident(session_factory, scope, tool):
    from svaar.actions.catalog import build_registry
    from svaar.actions.dispatcher import ApprovalPolicy, Dispatcher
    from svaar.actions.missions import Mission
    from svaar.actions.registry import Channel, ToolContext

    deliver(session_factory, run(run_id=1002, workflow_id=56))
    other = next(row.id for row in incidents(session_factory) if row.id != scope[2])
    dispatcher = Dispatcher(build_registry(), ApprovalPolicy(timedelta(minutes=10), 3, False))
    context = ToolContext(
        scope[0],
        scope[1],
        Channel.VOICE,
        Mission.ESCALATION,
        "bound-incident",
        incident_id=scope[2],
    )
    with session_factory.begin() as session:
        result = dispatcher.dispatch(session, context, tool, {"incident_id": str(other)})
        assert not result.output.get("found", result.output.get("acknowledged", False))
        assert session.get(Incident, other).state == "open"


def test_failed_job_does_not_stop_another_recipient(session_factory, scope):
    from factories import make_principal

    from svaar.identity.models import Org

    deliver(session_factory, run(run_id=1002, workflow_id=56))
    other_id = next(row.id for row in incidents(session_factory) if row.id != scope[2])
    with session_factory.begin() as session:
        owner = make_principal(session, session.get(Org, scope[0]), Role.DEV)
        session.get(Incident, other_id).owner_principal_id = owner.id
        session.add(
            ChannelBinding(
                principal_id=owner.id, channel="phone", address="+15555550124", verified_at=NOW
            )
        )
    instance = worker(session_factory)
    instance.alert_time = lambda *_: NOW - timedelta(seconds=601)

    def prepare(session, org, principal, incident):
        if incident == scope[2]:
            prepare_escalation_call(session, org, principal, incident)
            raise RuntimeError("simulated failure")
        return prepare_escalation_call(session, org, principal, incident)

    instance.prepare_call = prepare
    result = instance.run_once()
    assert result["failed"] == 1 and result["prepared"] == 1
    assert len(calls(session_factory)) == 1
