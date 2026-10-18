"""Error contracts must not reflect rejected input or exception details."""

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/missing")
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "http_404", "message": "Not Found"}}


def test_validation_omits_input_and_context(app: FastAPI, client: TestClient) -> None:
    class Input(BaseModel):
        count: int

    @app.post("/api/v1/test-only")
    def endpoint(body: Input) -> Input:
        return body

    response = client.post("/api/v1/test-only", json={"count": "private-token"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["details"][0]["location"] == ["body", "count"]
    assert "private-token" not in response.text


def test_http_exception_preserves_status_and_headers(app: FastAPI, client: TestClient) -> None:
    @app.get("/api/v1/test-only")
    def endpoint() -> None:
        raise HTTPException(401, "private-token", headers={"WWW-Authenticate": "Bearer"})

    response = client.get("/api/v1/test-only")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert "private-token" not in response.text


def test_unexpected_error_is_sanitized(app: FastAPI, client: TestClient) -> None:
    @app.get("/api/v1/test-only")
    def endpoint() -> None:
        raise RuntimeError("private-password")

    response = client.get("/api/v1/test-only")
    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "Internal server error"}
    }
