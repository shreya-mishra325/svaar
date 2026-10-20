"""Operator routes require the operator token and return invite codes once."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from svaar.app import create_app
from svaar.config import Settings

TOKEN = "operator-token-for-tests-only-0123456789"


@pytest.fixture
def operator_settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"operator_token": SecretStr(TOKEN)})


def test_operator_routes_unavailable_without_token(client: TestClient) -> None:
    response = client.post("/api/v1/orgs", json={"name": "Example"})
    assert response.status_code == 503


@pytest.mark.parametrize("header", [None, "Bearer wrong-token", f"Basic {TOKEN}"])
def test_operator_routes_reject_bad_credentials(
    operator_settings: Settings, header: str | None
) -> None:
    headers = {"Authorization": header} if header else {}
    with TestClient(create_app(operator_settings)) as client:
        response = client.post("/api/v1/orgs", json={"name": "Example"}, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.fixture
def operator_client(database_url: str, session_factory: object) -> Iterator[TestClient]:
    settings = Settings(_env_file=None, database_url=database_url, operator_token=TOKEN)
    with TestClient(create_app(settings)) as client:
        client.headers["Authorization"] = f"Bearer {TOKEN}"
        yield client


@pytest.mark.postgres
def test_create_org_and_invite(operator_client: TestClient) -> None:
    org = operator_client.post("/api/v1/orgs", json={"name": "Example"})
    assert org.status_code == 201
    invite = operator_client.post(
        "/api/v1/invites", json={"org_id": org.json()["id"], "role": "lead"}
    )
    assert invite.status_code == 201
    body = invite.json()
    assert body["role"] == "lead" and len(body["code"]) == 14


@pytest.mark.postgres
def test_invite_for_unknown_org_is_404(operator_client: TestClient) -> None:
    response = operator_client.post(
        "/api/v1/invites",
        json={"org_id": "00000000-0000-0000-0000-000000000000", "role": "dev"},
    )
    assert response.status_code == 404
