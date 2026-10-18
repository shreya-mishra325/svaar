"""Gateway checks must clean up connections and never simulate a running listener."""

from unittest.mock import MagicMock, patch

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
