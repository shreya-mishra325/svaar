"""Dispatch-time guards: current incident ownership, readiness and per-recipient limits."""

import pytest
from test_escalation_jobs import escalation_scope
from test_voice_calls import Provider

from svaar.app import create_call_service
from svaar.config import Settings
from svaar.incidents.models import Incident
from svaar.voice.calls import CallService, prepare_escalation_call
from svaar.voice.models import VoiceCall

pytestmark = pytest.mark.postgres


@pytest.fixture
def scope(session_factory):
    return escalation_scope(session_factory)


def settings(limit=3):
    return Settings(
        _env_file=None,
        database_url="postgresql+psycopg://test:test@127.0.0.1:1/test",
        voice_daily_call_limit=limit,
    )


def intent(sessions, scope):
    with sessions.begin() as session:
        return prepare_escalation_call(session, scope[0], scope[1], scope[2])


def test_escalation_is_rechecked_against_the_current_incident(session_factory, scope):
    call_id = intent(session_factory, scope)
    provider = Provider()
    assert CallService(session_factory, provider).place(scope[0], call_id) == "not_authorized"
    service = create_call_service(session_factory, provider, settings())
    with session_factory.begin() as session:
        session.get(Incident, scope[2]).state = "acknowledged"
    assert service.place(scope[0], call_id) == "not_authorized"
    with session_factory.begin() as session:
        session.get(Incident, scope[2]).state = "open"
    assert service.place(scope[0], call_id) == "queued"
    assert len(provider.placements) == 1
    with session_factory() as session:
        assert session.get(VoiceCall, call_id).placed_at is not None


def test_recipient_daily_limit_blocks_further_placement(session_factory, scope):
    first = intent(session_factory, scope)
    provider = Provider()
    service = create_call_service(session_factory, provider, settings(limit=1))
    assert service.place(scope[0], first) == "queued"
    with session_factory.begin() as session:
        # A finished call still counts toward the recipient's daily limit.
        session.get(VoiceCall, first).state = "closed"
        second = VoiceCall(
            org_id=scope[0],
            principal_id=scope[1],
            mission="escalation",
            incident_id=None,
            phone_binding_id=session.get(VoiceCall, first).phone_binding_id,
        )
        session.add(second)
        session.flush()
        second_id = second.id
    assert service.place(scope[0], second_id) == "call_limit_reached"
    assert len(provider.placements) == 1
    with session_factory() as session:
        assert session.get(VoiceCall, second_id).state == "pending"


@pytest.mark.parametrize("probe", [lambda: False, lambda: 1 / 0])
def test_unready_provider_never_dials(session_factory, scope, probe):
    call_id = intent(session_factory, scope)
    provider = Provider()
    service = create_call_service(session_factory, provider, settings(), ready=probe)
    assert service.place(scope[0], call_id) == "provider_not_ready"
    assert provider.placements == []
    with session_factory() as session:
        assert session.get(VoiceCall, call_id).state == "pending"
