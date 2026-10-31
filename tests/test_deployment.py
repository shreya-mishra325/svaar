"""Demo ingress boundaries, private preparation and worker heartbeat safety."""

import json
import stat
import time

import pytest
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from pydantic import SecretStr

from svaar.deployment import prepare
from svaar.ingress import create_demo_ingress
from svaar.jobs import heartbeat


def test_demo_env_is_exclusive_private_and_separate_from_development(tmp_path):
    source, output = tmp_path / "source", tmp_path / "demo"
    source.write_text("SVAAR_LLM_API_KEY='fake-provider'\nPOSTGRES_PASSWORD=svaar_dev_only\n")
    prepare(source, output)
    data = dotenv_values(output)
    assert data["SVAAR_LLM_API_KEY"] == "fake-provider"
    assert len(data["POSTGRES_PASSWORD"]) >= 36 and data["POSTGRES_PASSWORD"] != "svaar_dev_only"
    assert data["SVAAR_ENVIRONMENT"] == "production"
    assert data["SVAAR_GITHUB_ACTIONS_ENABLED"] == "false"
    assert (
        len(
            {
                data[key]
                for key in (
                    "SVAAR_OPERATOR_TOKEN",
                    "SVAAR_VOICE_STATUS_SECRET",
                    "SVAAR_VOICE_TURN_TOKEN",
                )
            }
        )
        == 3
    )
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        prepare(source, output)
    assert output.read_bytes() == before
    assert "svaar_dev_only" in source.read_text()


def test_public_origin_has_no_operator_docs_or_dispatch_routes(settings):
    configured = settings.model_copy(update={"voice_status_secret": SecretStr("s" * 32)})
    app = create_demo_ingress(configured)
    with TestClient(app, client=("127.0.0.1", 1234)) as client:
        assert client.get("/health").status_code == 200
        assert client.post("/api/v1/orgs", json={"name": "blocked"}).status_code == 404
        for path in ("/docs", "/openapi.json", "/api/v1/orgs", "/api/v1/incidents"):
            assert client.get(path).status_code == 404
        assert client.post("/api/v1/voice/status").status_code == 401
        assert client.post("/api/v1/webhooks/github").status_code == 503


def test_forwarded_headers_do_not_manufacture_a_loopback_peer(settings):
    app = create_demo_ingress(
        settings.model_copy(update={"voice_status_secret": SecretStr("s" * 32)})
    )
    with TestClient(app, client=("172.20.0.8", 1234)) as client:
        assert (
            client.get(
                "/health",
                headers={
                    "X-Forwarded-For": "127.0.0.1",
                    "CF-Connecting-IP": "127.0.0.1",
                },
            ).status_code
            == 403
        )


def test_voice_token_and_status_ip_requirements_remain_separate(settings):
    configured = settings.model_copy(
        update={
            "voice_status_secret": SecretStr("s" * 32),
            "voice_turn_token": SecretStr("t" * 32),
            "voice_turn_mode": "llm_endpoint",
        }
    )
    with TestClient(create_demo_ingress(configured), client=("127.0.0.1", 1234)) as client:
        assert client.get("/api/v1/voice/llm/models").status_code == 401
        assert (
            client.get(
                "/api/v1/voice/llm/models", headers={"Authorization": "Bearer " + "t" * 32}
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/v1/voice/status",
                headers={
                    "X-Svaar-Voice-Status-Secret": "s" * 32,
                    "CF-Connecting-IP": "192.0.2.4",
                },
            ).status_code
            == 403
        )


def test_heartbeat_is_fresh_and_fail_closed(tmp_path):
    path = tmp_path / "heartbeat"
    assert not heartbeat.healthy(60, path=path)
    heartbeat.record("ready", path=path)
    assert heartbeat.healthy(60, path=path)
    heartbeat.record("error", path=path)
    assert not heartbeat.healthy(60, path=path)
    path.write_text(json.dumps({"state": "ready", "at": time.time() - 100}))
    assert not heartbeat.healthy(60, path=path)
    path.write_text(json.dumps({"state": "ready", "at": time.time() + 100}))
    assert not heartbeat.healthy(60, path=path)
