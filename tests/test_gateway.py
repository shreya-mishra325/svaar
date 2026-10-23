"""Gateway checks must clean up connections and never simulate a running listener."""

from unittest.mock import MagicMock, Mock, patch

import pytest
from sqlalchemy.exc import OperationalError

from svaar.config import Settings
from svaar.gateway import main


def test_gateway_refuses_start_without_agent_runtime(settings: Settings) -> None:
    with (
        patch("svaar.gateway.Settings", return_value=settings),
        patch("svaar.gateway.create_database_engine") as factory,
    ):
        assert main([]) == 2
    factory.assert_not_called()


def test_gateway_requires_configuration() -> None:
    # Avoid consulting a developer's .env while exercising real validation.
    with patch("svaar.gateway.Settings", side_effect=lambda: Settings(_env_file=None)):
        assert main(["--check"]) == 2


@pytest.mark.parametrize("available", [True, False])
def test_gateway_database_check_disposes_resources(settings: Settings, available: bool) -> None:
    engine = MagicMock()
    if not available:
        engine.connect.side_effect = OperationalError("private SQL", {}, Exception("private-token"))
    with (
        patch("svaar.gateway.Settings", return_value=settings),
        patch("svaar.gateway.create_database_engine", return_value=engine),
    ):
        assert main(["--check"]) == (0 if available else 1)
    engine.dispose.assert_called_once_with()
    if available:
        connection = engine.connect.return_value.__enter__.return_value
        assert str(connection.execute.call_args.args[0]) == "SELECT 1"
        engine.connect.return_value.__exit__.assert_called_once()


def test_missing_caspian_configuration_blocks_start_without_any_provider_call(settings):
    configured = settings.model_copy(
        update={
            "channel_transport": "caspian",
            "llm_model": "test",
        }
    )
    with (
        patch("svaar.gateway.Settings", return_value=configured),
        patch("svaar.gateway.CaspianTelegramTransport.from_settings", side_effect=ValueError),
        patch("svaar.gateway.create_database_engine") as engine,
    ):
        assert main([]) == 2
    engine.assert_not_called()


def test_runtime_composition_closes_all_resources_without_inference(settings):
    configured = settings.model_copy(
        update={
            "channel_transport": "caspian",
            "llm_model": "test",
            "caspian_telegram_connection_id": "connection-1",
        }
    )
    transport, engine, model, worker = Mock(), MagicMock(), Mock(), Mock()
    with (
        patch("svaar.gateway.Settings", return_value=configured),
        patch("svaar.gateway.CaspianTelegramTransport.from_settings", return_value=transport),
        patch("svaar.gateway.create_database_engine", return_value=engine),
        patch("svaar.gateway.HttpChatModel.from_settings", return_value=model),
        patch("svaar.gateway.GatewayWorker", return_value=worker),
    ):
        assert main([]) == 0
    worker.run.assert_called_once()
    transport.check_connection.assert_called_once()
    transport.close.assert_called_once()
    model.close.assert_called_once()
    model.complete.assert_not_called()
    engine.dispose.assert_called_once()
