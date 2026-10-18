"""Shared fixtures isolate configuration and never read a developer's .env."""

import os
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from svaar.app import create_app
from svaar.config import Settings


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
