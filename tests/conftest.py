"""Shared fixtures isolate configuration and never read a developer's .env."""

import os
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from svaar.app import create_app
from svaar.config import Settings
from svaar.db import create_database_engine


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove application settings inherited from the shell for each test."""
    for name in os.environ:
        if name.startswith("SVAAR_") and name != "SVAAR_TEST_DATABASE_URL":
            monkeypatch.delenv(name)


@pytest.fixture
def settings() -> Settings:
    """Return settings with no live credentials or configuration-file access."""
    return Settings(
        _env_file=None,
        environment="test",
        database_url="postgresql+psycopg://test:test@127.0.0.1:1/test",
        database_timeout_seconds=1,
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    """Create the application without opening a database connection."""
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Run the full startup/shutdown lifecycle for each client."""
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


DOMAIN_TABLES = (
    "escalation_jobs",
    "evidence",
    "claims",
    "workflow_log_signatures",
    "replay_runs",
    "negotiation_rounds",
    "negotiations",
    "incident_events",
    "incidents",
    "webhook_deliveries",
    "events",
    "repo_mappings",
    "voice_webhook_events",
    "voice_turns",
    "voice_calls",
    "phone_challenges",
    "gateway_cursors",
    "outbox_messages",
    "messages",
    "inbound_messages",
    "conversations",
    "invites",
    "channel_bindings",
    "principals",
    "orgs",
    "confirmations",
    "tool_executions",
    "decisions",
)


@pytest.fixture(scope="session")
def database_url() -> str:
    """Return the dedicated test database URL, migrated to head, or skip."""
    url = os.environ.get("SVAAR_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set SVAAR_TEST_DATABASE_URL to a dedicated PostgreSQL test database")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("SVAAR_DATABASE_URL", url)
        command.upgrade(Config("alembic.ini"), "head")
    return url


@pytest.fixture(scope="session")
def db_engine(database_url: str) -> Iterator[Engine]:
    """Share one engine across database tests."""
    engine = create_database_engine(
        Settings(_env_file=None, database_url=database_url, database_timeout_seconds=10)
    )
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(db_engine: Engine) -> Iterator[sessionmaker[Session]]:
    """Provide sessions that commit for real; domain tables are emptied afterwards."""
    yield sessionmaker(bind=db_engine, expire_on_commit=False)
    with db_engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {', '.join(DOMAIN_TABLES)} CASCADE"))


@pytest.fixture
def db_session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Yield one session against the migrated test database."""
    with session_factory() as session:
        yield session
