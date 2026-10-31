"""Render-specific ingress and startup checks; no live provider calls."""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from svaar.render_ingress import create_render_app
from svaar.render_start import main, normalized_database_url
from svaar.voice.status import HEADER


@pytest.fixture
def render_environment(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("RENDER_SERVICE_TYPE", "web")
    monkeypatch.setenv("RENDER_EXTERNAL_HOSTNAME", "svaar-check.onrender.com")


@pytest.fixture
def render_settings(settings):
    return settings.model_copy(
        update={
            "environment": "production",
            "voice_status_secret": SecretStr("s" * 32),
            "voice_turn_mode": "llm_endpoint",
            "voice_turn_token": SecretStr("t" * 32),
        }
    )


def test_render_factory_refuses_generic_proxy(settings):
    with pytest.raises(ValueError, match="metadata"):
        create_render_app(settings)


def test_postgres_alias_preserves_ssl_and_secret():
    from sqlalchemy.engine import make_url

    url = make_url(normalized_database_url("postgres://user:fake%40secret@db/test?sslmode=require"))
    assert url.drivername == "postgresql+psycopg"
    assert url.password == "fake@secret" and url.query["sslmode"] == "require"
    with pytest.raises(ValueError):
        normalized_database_url("sqlite:///test")


def test_render_isolation_and_host_validation(render_environment, render_settings):
    with TestClient(
        create_render_app(render_settings), base_url="https://svaar-check.onrender.com"
    ) as client:
        assert client.get("/health").status_code == 200
        for path in (
            "/api/v1/orgs",
            "/api/v1/invites",
            "/docs",
            "/openapi.json",
            "/api/v1/voice/turn",
            "/api/v1/voice/status/",
        ):
            assert client.post(path, json={}).status_code == 404
        assert client.get("/health", headers={"Host": "attacker.example"}).status_code == 400
        assert client.get("/api/v1/voice/llm/models").status_code == 401
        assert (
            client.get(
                "/api/v1/voice/llm/models", headers={"Authorization": "Bearer " + "t" * 32}
            ).status_code
            == 200
        )


@pytest.mark.parametrize(
    "headers,expected",
    [
        ({}, 401),
        ({HEADER: "s" * 32}, 403),
        ({HEADER: "s" * 32, "x-forwarded-for": "13.203.39.153"}, 403),
        ({HEADER: "s" * 32, "cf-connecting-ip": "192.0.2.4"}, 403),
        ({HEADER: "s" * 32, "cf-connecting-ip": "13.203.39.153, 192.0.2.4"}, 403),
        ({HEADER: "s" * 32, "cf-connecting-ip": "13.203.39.153"}, 422),
    ],
)
def test_render_retains_secret_and_allowlist(
    render_environment, render_settings, headers, expected
):
    with TestClient(
        create_render_app(render_settings),
        base_url="https://svaar-check.onrender.com",
        client=("10.0.0.8", 1234),
    ) as client:
        assert (
            client.post("/api/v1/voice/status", headers=headers, content=b"invalid").status_code
            == expected
        )


def test_duplicate_edge_assertion_rejected(render_environment, render_settings):
    with TestClient(
        create_render_app(render_settings), base_url="https://svaar-check.onrender.com"
    ) as client:
        assert (
            client.post(
                "/api/v1/voice/status",
                headers=[
                    (HEADER, "s" * 32),
                    ("cf-connecting-ip", "13.203.39.153"),
                    ("cf-connecting-ip", "13.203.39.153"),
                ],
                content=b"invalid",
            ).status_code
            == 403
        )


def test_invalid_port_never_migrates_or_executes(render_environment, monkeypatch):
    monkeypatch.setenv("PORT", "10000;invalid")
    migrate, execute = Mock(), Mock()
    monkeypatch.setattr("svaar.render_start.migrate", migrate)
    monkeypatch.setattr("svaar.render_start.os.execvp", execute)
    assert main() == 1
    migrate.assert_not_called()
    execute.assert_not_called()


def test_migration_failure_never_starts_http(render_environment, render_settings, monkeypatch):
    monkeypatch.setenv("SVAAR_DATABASE_URL", render_settings.database_url.get_secret_value())
    monkeypatch.setattr("svaar.render_start.Settings", lambda **_: render_settings)
    monkeypatch.setattr("svaar.render_start.migrate", Mock(side_effect=RuntimeError("simulated")))
    execute = Mock()
    monkeypatch.setattr("svaar.render_start.os.execvp", execute)
    assert main() == 1
    execute.assert_not_called()


def test_successful_start_migrates_then_execs_one_restricted_worker(
    render_environment,
    render_settings,
    monkeypatch,
):
    monkeypatch.setenv("SVAAR_DATABASE_URL", render_settings.database_url.get_secret_value())
    monkeypatch.setenv("PORT", "10001")
    monkeypatch.setattr("svaar.render_start.Settings", lambda **_: render_settings)
    events = []
    monkeypatch.setattr("svaar.render_start.migrate", lambda _: events.append("migrated"))
    monkeypatch.setattr("svaar.render_start.os.execvp", lambda _, args: events.append(args))
    assert main() == 0
    assert events[0] == "migrated"
    assert "svaar.render_ingress:create_render_app" in events[1]
    assert events[1][events[1].index("--port") + 1] == "10001"
    assert events[1][events[1].index("--workers") + 1] == "1"
    assert "--no-proxy-headers" in events[1]
