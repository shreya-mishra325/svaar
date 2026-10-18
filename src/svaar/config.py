"""Validated environment configuration; no resources are created on import."""

from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    """Load SVAAR_ variables and an optional local .env file."""

    model_config = SettingsConfigDict(
        env_prefix="SVAAR_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: SecretStr
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_timeout_seconds: int = Field(default=3, ge=1, le=30)

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        """Require a complete PostgreSQL URL using the psycopg driver."""
        try:
            url = make_url(value.get_secret_value())
        except (ArgumentError, ValueError):
            raise ValueError("A valid PostgreSQL connection URL is required") from None
        if url.drivername not in {"postgresql", "postgresql+psycopg"}:
            raise ValueError("Use postgresql:// or postgresql+psycopg://")
        if not all((url.username, url.password, url.host, url.database)):
            raise ValueError("Database URL requires username, password, host, and database")
        return value
