"""Configuration validation and credential-display safety checks."""

import pytest
from pydantic import ValidationError

from svaar.config import Settings

URL = "postgresql+psycopg://test:example_password@localhost:5432/test"


def test_database_url_is_required() -> None:
    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)


def test_environment_loading_and_secret_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SVAAR_DATABASE_URL", URL)
    monkeypatch.setenv("SVAAR_ENVIRONMENT", "test")
    settings = Settings(_env_file=None)
    assert settings.environment == "test"
    assert settings.database_url.get_secret_value() == URL
    assert "example_password" not in repr(settings)
    assert "example_password" not in settings.model_dump_json()


@pytest.mark.parametrize(
    "url",
    ["", "invalid", "sqlite:///test.db", "postgresql://localhost/test", "postgresql://u:p@host"],
)
def test_invalid_database_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=url)


@pytest.mark.parametrize(
    "overrides",
    [{"environment": "unknown"}, {"log_level": "TRACE"}, {"database_timeout_seconds": 0}],
)
def test_invalid_settings_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=URL, **overrides)


def test_validation_error_string_hides_input() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, database_url="https://user:example_password@host/db")
    assert "example_password" not in str(error.value)
