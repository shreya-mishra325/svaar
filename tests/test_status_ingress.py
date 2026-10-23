"""Restricted Cloudflare origin behavior, entirely synthetic HTTP."""

import uuid

import pytest
from fastapi.testclient import TestClient

from svaar.app import create_app, create_status_ingress
from svaar.config import Settings
from svaar.voice.status import HEADER

SECRET = "s" * 32


def configured(settings):
    return Settings(_env_file=None, database_url=settings.database_url, voice_status_secret=SECRET)


def test_ingress_requires_configured_secret(settings):
    with pytest.raises(ValueError, match="separate voice status secret"):
        create_status_ingress(settings)


@pytest.mark.parametrize(
    "path",
    [
        "/docs",
        "/openapi.json",
        "/health",
        "/ready",
        "/api/v1/invites",
        "/api/v1/repo-mappings",
        "/api/v1/webhooks/github",
        "/api/v1/voice/turn",
        "/api/v1/voice/status/",
        "/",
    ],
)
def test_ingress_exposes_only_exact_status_path(settings, path):
    with TestClient(
        create_status_ingress(configured(settings)), client=("127.0.0.1", 50000)
    ) as client:
        for method in ("GET", "POST"):
            assert client.request(method, path).status_code == 404


@pytest.mark.parametrize(
    "peer,headers,expected",
    [
        ("127.0.0.1", {}, 401),
        ("127.0.0.1", {HEADER: SECRET}, 403),
        ("127.0.0.1", {HEADER: SECRET, "cf-connecting-ip": "203.0.113.1"}, 403),
        ("127.0.0.1", {HEADER: SECRET, "x-forwarded-for": "13.203.39.153"}, 403),
        ("127.0.0.1", {HEADER: SECRET, "cf-connecting-ip": "13.203.39.153, 203.0.113.1"}, 403),
        ("127.0.0.1", {HEADER: SECRET, "cf-connecting-ip": " 13.203.39.153"}, 403),
        ("203.0.113.1", {HEADER: SECRET, "cf-connecting-ip": "13.203.39.153"}, 403),
        ("13.203.39.153", {HEADER: SECRET, "cf-connecting-ip": "13.203.39.153"}, 403),
        ("127.0.0.1", {HEADER: SECRET, "cf-connecting-ip": "13.203.39.153"}, 422),
        ("127.0.0.1", {HEADER: SECRET, "cf-connecting-ip": "13.126.9.249"}, 422),
        ("127.0.0.1", {HEADER: SECRET, "cf-connecting-ip": "13.202.133.53"}, 422),
    ],
)
def test_cloudflare_header_trust_is_scoped(settings, peer, headers, expected):
    with TestClient(create_status_ingress(configured(settings)), client=(peer, 50000)) as client:
        assert (
            client.post("/api/v1/voice/status", headers=headers, content=b"invalid").status_code
            == expected
        )


def test_duplicate_cloudflare_headers_rejected(settings):
    with TestClient(
        create_status_ingress(configured(settings)), client=("127.0.0.1", 50000)
    ) as client:
        response = client.post(
            "/api/v1/voice/status",
            headers=[
                (HEADER, SECRET),
                ("cf-connecting-ip", "13.203.39.153"),
                ("cf-connecting-ip", "13.203.39.153"),
            ],
            content=b"invalid",
        )
        assert response.status_code == 403


def test_normal_app_never_trusts_cloudflare_header(settings):
    with TestClient(create_app(configured(settings)), client=("127.0.0.1", 50000)) as client:
        response = client.post(
            "/api/v1/voice/status",
            headers={
                HEADER: SECRET,
                "cf-connecting-ip": "13.203.39.153",
            },
            content=b"invalid",
        )
        assert response.status_code == 403


def test_allowed_ingress_reaches_existing_status_handler(settings, monkeypatch):
    seen = []

    def ingest(sessions, payload, raw, notify):
        seen.append(payload.status)
        return "duplicate"

    monkeypatch.setattr("svaar.voice.status.ingest_status", ingest)
    with TestClient(
        create_status_ingress(configured(settings)), client=("127.0.0.1", 50000)
    ) as client:
        assert client.app.state.voice_turn_runner is None
        response = client.post(
            "/api/v1/voice/status",
            headers={
                HEADER: SECRET,
                "cf-connecting-ip": "13.203.39.153",
            },
            json={"id": str(uuid.uuid4()), "agent_id": str(uuid.uuid4()), "status": "completed"},
        )
        assert response.status_code == 200
        assert response.json() == {"status": "duplicate"}
        assert seen == ["completed"]
