"""Validated environment configuration; no resources are created on import."""

import math
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

MIN_TOKEN_LENGTH = 32


class Settings(BaseSettings):
    """Load SVAAR_ variables and an optional local .env file.

    Feature credentials are optional at construction so each process requires only
    the credentials it uses. A missing credential disables its feature; it never
    falls back to a usable default.
    """

    model_config = SettingsConfigDict(
        env_prefix="SVAAR_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: SecretStr
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_timeout_seconds: int = Field(default=3, ge=1, le=30)

    # Operator routes only; voice, channel and webhook routes use separate credentials.
    operator_token: SecretStr | None = None

    # Identity and approvals.
    invite_ttl_hours: int = Field(default=72, ge=1, le=720)
    confirmation_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    confirmation_max_attempts: int = Field(default=5, ge=1, le=10)
    allow_same_channel_confirmation: bool = False

    # Decision policy thresholds; tune on labelled transcripts, not vendor claims.
    policy_high: float = Field(default=0.85, ge=0.0, le=1.0)
    policy_low: float = Field(default=0.55, ge=0.0, le=1.0)

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

    @field_validator("operator_token", mode="before")
    @classmethod
    def empty_token_is_unset(cls, value: object) -> object:
        """Treat an empty variable, as copied from .env.example, as not configured."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("operator_token")
    @classmethod
    def validate_token_strength(cls, value: SecretStr | None) -> SecretStr | None:
        """Reject short bearer tokens that could be guessed."""
        if value is not None and len(value.get_secret_value()) < MIN_TOKEN_LENGTH:
            raise ValueError(f"Tokens must be at least {MIN_TOKEN_LENGTH} characters")
        return value

    @model_validator(mode="after")
    def validate_policy_thresholds(self) -> Self:
        """Require finite thresholds with low strictly below high."""
        if not (math.isfinite(self.policy_low) and math.isfinite(self.policy_high)):
            raise ValueError("Policy thresholds must be finite")
        if self.policy_low >= self.policy_high:
            raise ValueError("SVAAR_POLICY_LOW must be below SVAAR_POLICY_HIGH")
        return self
