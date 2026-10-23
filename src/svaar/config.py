"""Validated environment configuration; no resources are created on import."""

import math
import uuid
from typing import Literal, Self

import httpx
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

    # One optional model configuration serves chat and voice. All three or none.
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str | None = None

    channel_transport: Literal["caspian", "telegram"] | None = None
    gateway_poll_seconds: float = Field(default=2.0, ge=0.1, le=30.0)
    gateway_batch_size: int = Field(default=10, ge=1, le=100)

    # Hosted Caspian Telegram adapter; credentials alone never start a listener.
    caspian_base_url: str | None = None
    caspian_api_key: SecretStr | None = None
    caspian_telegram_connection_id: str | None = Field(default=None, repr=False)
    caspian_telegram_address: str | None = Field(default=None, repr=False)

    # Optional standalone Bolna adapter; no automatic calls or voice routes.
    bolna_api_key: SecretStr | None = None
    bolna_agent_id: uuid.UUID | None = None

    # GitHub inbound HMAC only; not GitHub App/API access.
    github_webhook_secret: SecretStr | None = None

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

    @field_validator(
        "operator_token",
        "github_webhook_secret",
        "bolna_api_key",
        "bolna_agent_id",
        "channel_transport",
        "llm_api_key",
        "llm_base_url",
        "llm_model",
        "caspian_base_url",
        "caspian_api_key",
        "caspian_telegram_connection_id",
        "caspian_telegram_address",
        mode="before",
    )
    @classmethod
    def empty_token_is_unset(cls, value: object) -> object:
        """Treat an empty variable, as copied from .env.example, as not configured."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("operator_token", "github_webhook_secret")
    @classmethod
    def validate_token_strength(cls, value: SecretStr | None) -> SecretStr | None:
        """Reject short bearer tokens that could be guessed."""
        if value is not None and len(value.get_secret_value()) < MIN_TOKEN_LENGTH:
            raise ValueError(f"Tokens must be at least {MIN_TOKEN_LENGTH} characters")
        return value

    @field_validator("llm_base_url")
    @classmethod
    def validate_llm_url(cls, value: str | None) -> str | None:
        """Require an HTTP(S) endpoint without embedded credentials or query secrets."""
        if value is None:
            return None
        try:
            url = httpx.URL(value)
        except httpx.InvalidURL:
            raise ValueError("Invalid LLM base URL") from None
        if (
            url.scheme not in {"http", "https"}
            or not url.host
            or url.userinfo
            or url.query
            or url.fragment
        ):
            raise ValueError(
                "LLM URL requires HTTP(S), a host, and no credentials, query or fragment"
            )
        return value.rstrip("/")

    @field_validator("caspian_base_url")
    @classmethod
    def validate_caspian_url(cls, value: str | None) -> str | None:
        """Constrain credentials to the verified hosted endpoint."""
        if value is None:
            return None
        if value.rstrip("/") != "https://api.trycaspianai.com":
            raise ValueError("Use the verified Caspian HTTPS endpoint")
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_llm_configuration(self) -> Self:
        """A partial model configuration must fail before application startup."""
        configured = (self.llm_base_url, self.llm_api_key, self.llm_model)
        if any(configured) and not all(configured):
            raise ValueError(
                "Set SVAAR_LLM_BASE_URL, SVAAR_LLM_API_KEY and SVAAR_LLM_MODEL together"
            )
        return self

    @model_validator(mode="after")
    def validate_policy_thresholds(self) -> Self:
        """Require finite thresholds with low strictly below high."""
        if not (math.isfinite(self.policy_low) and math.isfinite(self.policy_high)):
            raise ValueError("Policy thresholds must be finite")
        if self.policy_low >= self.policy_high:
            raise ValueError("SVAAR_POLICY_LOW must be below SVAAR_POLICY_HIGH")
        return self
