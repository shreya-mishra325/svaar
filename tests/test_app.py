"""Lifecycle, liveness, and readiness behavior with controlled database outcomes."""

from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from svaar.app import create_app
from svaar.config import Settings


def test_lifecycle_disposes_engine(app: FastAPI) -> None:
    assert not hasattr(app.state, "engine")
    with TestClient(app):
        engine = app.state.engine
        engine.dispose = Mock(wraps=engine.dispose)
        spy = engine.dispose
        assert app.state.session_factory.kw["bind"] is engine
    spy.assert_called_once_with()
    assert not hasattr(app.state, "engine")
    assert not hasattr(app.state, "session_factory")


def test_health_does_not_connect(client: TestClient, app: FastAPI) -> None:
    with patch.object(app.state.engine, "connect") as connect:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    connect.assert_not_called()


def test_ready_executes_query_and_closes_connection(client: TestClient, app: FastAPI) -> None:
    with patch.object(app.state.engine, "connect") as connect:
        connection = connect.return_value.__enter__.return_value
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert str(connection.execute.call_args.args[0]) == "SELECT 1"
    connect.return_value.__exit__.assert_called_once()


def test_ready_sanitizes_database_errors(client: TestClient, app: FastAPI) -> None:
    error = OperationalError("private SQL", {}, Exception("private-password"))
    with patch.object(app.state.engine, "connect", side_effect=error):
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
    assert "private" not in response.text
    assert client.get("/health").status_code == 200


def test_ready_fails_when_database_port_is_unreachable(client: TestClient) -> None:
    assert client.get("/ready").status_code == 503


def test_production_disables_documentation(settings: Settings) -> None:
    production = settings.model_copy(update={"environment": "production"})
    with TestClient(create_app(production)) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404


@pytest.mark.parametrize("close_fails", [False, True])
def test_configured_agent_lifecycle_does_not_call_provider(
    settings: Settings, close_fails: bool
) -> None:
    configured = Settings(
        _env_file=None,
        database_url=settings.database_url,
        llm_base_url="https://example.invalid/v1",
        llm_api_key="example-only",
        llm_model="test-model",
    )
    model = Mock()
    if close_fails:
        model.close.side_effect = RuntimeError("close failed")
    app = create_app(configured)

    def lifecycle() -> None:
        with TestClient(app):
            assert app.state.agent_loop is not None
            assert app.state.chat_runtime.agent is app.state.agent_loop
            app.state.engine.dispose = Mock(wraps=app.state.engine.dispose)
            disposals.append(app.state.engine.dispose)
            model.complete.assert_not_called()

    disposals = []
    with patch("svaar.app.HttpChatModel.from_settings", return_value=model):
        if close_fails:
            with pytest.raises(RuntimeError, match="close failed"):
                lifecycle()
        else:
            lifecycle()
    model.close.assert_called_once_with()
    disposals[0].assert_called_once_with()
    assert not hasattr(app.state, "agent_loop")
    assert not hasattr(app.state, "chat_runtime")
    assert not hasattr(app.state, "engine")
