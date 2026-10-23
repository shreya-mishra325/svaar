"""Status ingress security and durable replay behavior, no live providers."""

import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from factories import make_org, make_principal
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from svaar.app import create_app
from svaar.config import Settings
from svaar.identity.models import ChannelBinding
from svaar.voice.models import VoiceCall, VoiceWebhookEvent
from svaar.voice.status import HEADER, MAX_BODY_BYTES, StatusPayload, ingest_status

SECRET = "s" * 32
AGENT = uuid.uuid4()
EXECUTION = uuid.uuid4()


@pytest.fixture
def call_id(session_factory):
    with session_factory() as session:
        org = make_org(session)
        principal = make_principal(session, org, bindings=(("phone", "+15555550123"),))
        binding = session.scalar(select(ChannelBinding))
        call = VoiceCall(
            org_id=org.id,
            principal_id=principal.id,
            phone_binding_id=binding.id,
            mission="escalation",
            execution_id=EXECUTION,
            provider_agent_id=AGENT,
            provider_status="queued",
            state="queued",
        )
        session.add(call)
        session.commit()
        return call.id


def payload(status="completed"):
    return {
        "id": str(EXECUTION),
        "agent_id": str(AGENT),
        "status": status,
        "transcript": "private-transcript",
    }


def test_status_replay_and_reordering(session_factory, call_id, database_url):
    settings = Settings(_env_file=None, database_url=database_url, voice_status_secret=SECRET)
    with TestClient(create_app(settings), client=("13.203.39.153", 50000)) as client:
        for status, expected in [
            ("in-progress", "recorded"),
            ("ringing", "ignored"),
            ("call-disconnected", "recorded"),
            ("completed", "recorded"),
            ("completed", "duplicate"),
            ("in-progress", "duplicate"),
            ("busy", "ignored"),
            ("future-status", "ignored"),
        ]:
            response = client.post(
                "/api/v1/voice/status", headers={HEADER: SECRET}, json=payload(status)
            )
            assert response.status_code == 200
            assert response.json() == {"status": expected}
        wrong = payload()
        wrong["agent_id"] = str(uuid.uuid4())
        assert (
            client.post("/api/v1/voice/status", headers={HEADER: SECRET}, json=wrong).status_code
            == 404
        )
        wrong["id"] = str(uuid.uuid4())
        assert (
            client.post("/api/v1/voice/status", headers={HEADER: SECRET}, json=wrong).status_code
            == 404
        )
    with session_factory() as session:
        call = session.get(VoiceCall, call_id)
        assert call.state == "closed" and call.provider_status == "completed"
        receipts = session.scalars(select(VoiceWebhookEvent)).all()
        assert len(receipts) == 6
        assert all("private" not in receipt.payload_hash for receipt in receipts)


@pytest.mark.parametrize(
    "peer,secret,headers,expected",
    [
        ("13.203.39.153", None, {}, 503),
        ("13.203.39.153", SECRET, {}, 401),
        ("13.203.39.153", SECRET, {HEADER: "wrong"}, 401),
        ("127.0.0.1", SECRET, {HEADER: SECRET, "X-Forwarded-For": "13.203.39.153"}, 403),
        ("13.203.39.153", SECRET, {HEADER: SECRET}, 422),
    ],
)
def test_auth_before_database(settings, peer, secret, headers, expected):
    configured = settings.model_copy(update={"voice_status_secret": None})
    if secret:
        configured = Settings(
            _env_file=None, database_url=settings.database_url, voice_status_secret=secret
        )
    with TestClient(create_app(configured), client=(peer, 50000)) as client:
        response = client.post("/api/v1/voice/status", headers=headers, content=b"invalid-json")
        assert response.status_code == expected


def test_bounded_and_ambiguous_payloads(settings):
    configured = Settings(
        _env_file=None, database_url=settings.database_url, voice_status_secret=SECRET
    )
    with TestClient(create_app(configured), client=("13.203.39.153", 50000)) as client:
        headers = {HEADER: SECRET}
        assert (
            client.post(
                "/api/v1/voice/status", headers=headers, content=b"x" * (MAX_BODY_BYTES + 1)
            ).status_code
            == 413
        )
        assert (
            client.post(
                "/api/v1/voice/status", headers=headers, content=b'{"id":1,"id":2}'
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/voice/status", headers=[(HEADER, SECRET), (HEADER, SECRET)], json=payload()
            ).status_code
            == 401
        )


def test_concurrent_duplicate_receipt(session_factory, call_id):
    body = StatusPayload.model_validate(payload())
    raw = json.dumps(payload()).encode()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: ingest_status(session_factory, body, raw), range(2)))
    assert sorted(results) == ["duplicate", "recorded"]
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(VoiceWebhookEvent)) == 1


def test_locally_closed_call_records_terminal_without_reopening(session_factory, call_id):
    with session_factory() as session:
        session.get(VoiceCall, call_id).state = "closed"
        session.commit()
    for status, expected in [("in-progress", "ignored"), ("completed", "recorded")]:
        assert (
            ingest_status(
                session_factory,
                StatusPayload.model_validate(payload(status)),
                json.dumps(payload(status)).encode(),
            )
            == expected
        )
    with session_factory() as session:
        call = session.get(VoiceCall, call_id)
        assert call.state == "closed" and call.provider_status == "completed"


def test_status_receipt_and_state_rollback_together(session_factory, call_id, monkeypatch):
    from sqlalchemy.orm import Session

    def fail_commit(self):
        raise RuntimeError("synthetic-commit-failure")

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="synthetic-commit-failure"):
            ingest_status(
                session_factory,
                StatusPayload.model_validate(payload()),
                json.dumps(payload()).encode(),
            )
    with session_factory() as session:
        assert session.get(VoiceCall, call_id).state == "queued"
        assert session.scalar(select(func.count()).select_from(VoiceWebhookEvent)) == 0


def test_status_secret_strength_and_blank(settings):
    from pydantic import ValidationError

    assert (
        Settings(
            _env_file=None, database_url=settings.database_url, voice_status_secret=""
        ).voice_status_secret
        is None
    )
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=settings.database_url, voice_status_secret="short")
