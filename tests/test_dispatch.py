"""Explicit operator dispatch applies every guard and never prints phone numbers."""

import json

import pytest
from test_escalation_jobs import escalation_scope
from test_voice_calls import Provider

from svaar.config import Settings
from svaar.dispatch import main
from svaar.incidents.models import Incident
from svaar.voice.calls import prepare_escalation_call
from svaar.voice.models import VoiceCall

pytestmark = pytest.mark.postgres


class Bolna(Provider):
    def __init__(self, ready=True):
        super().__init__()
        self.is_ready, self.closed = ready, False

    def readiness(self):
        return type("Readiness", (), {"ready": self.is_ready})()

    def close(self):
        self.closed = True


@pytest.fixture
def scope(session_factory):
    org_id, owner, incident_id = escalation_scope(session_factory)
    with session_factory.begin() as session:
        call_id = prepare_escalation_call(session, org_id, owner, incident_id)
    return org_id, owner, incident_id, call_id


def run(database_url, capsys, *argv, provider=None):
    def settings():
        return Settings(_env_file=None, database_url=database_url)

    code = main(list(argv), provider_factory=lambda _: provider, settings_factory=settings)
    return code, json.loads(capsys.readouterr().out)


def test_list_shows_pending_intents_without_phone_numbers(database_url, scope, capsys):
    code, rows = run(database_url, capsys, "--list")
    assert code == 0 and [row["call_id"] for row in rows] == [str(scope[3])]
    assert "+1555" not in json.dumps(rows)


def test_place_applies_guards_readiness_and_dials_once(
    database_url, session_factory, scope, capsys
):
    org, call = str(scope[0]), str(scope[3])
    unready = Bolna(ready=False)
    assert run(database_url, capsys, "--place", call, "--org", org, provider=unready) == (
        1,
        {"outcome": "provider_not_ready"},
    )
    assert unready.placements == [] and unready.closed
    with session_factory.begin() as session:
        session.get(Incident, scope[2]).state = "acknowledged"
    refused = Bolna()
    assert run(database_url, capsys, "--place", call, "--org", org, provider=refused)[1] == {
        "outcome": "not_authorized"
    }
    assert refused.placements == []
    with session_factory.begin() as session:
        session.get(Incident, scope[2]).state = "open"
    ready = Bolna()
    assert run(database_url, capsys, "--place", call, "--org", org, provider=ready) == (
        0,
        {"outcome": "queued"},
    )
    assert len(ready.placements) == 1
    again = Bolna()
    assert run(database_url, capsys, "--place", call, "--org", org, provider=again)[1] == {
        "outcome": "queued"
    }
    assert again.placements == []  # a placed intent is never dialed twice
    with session_factory() as session:
        assert session.get(VoiceCall, scope[3]).state == "queued"


def test_place_requires_an_organization(database_url, scope):
    with pytest.raises(SystemExit):
        main(
            ["--place", str(scope[3])],
            provider_factory=lambda _: Bolna(),
            settings_factory=lambda: Settings(_env_file=None, database_url=database_url),
        )
