"""Opt-in real PostgreSQL migration, session, and readiness checks."""

import os

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import text

from svaar.app import create_app
from svaar.config import Settings


@pytest.mark.postgres
def test_postgres_migrations_and_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    url = os.environ.get("SVAAR_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set SVAAR_TEST_DATABASE_URL to a dedicated PostgreSQL test database")
    monkeypatch.setenv("SVAAR_DATABASE_URL", url)
    monkeypatch.setenv("SVAAR_ENVIRONMENT", "test")
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    command.check(config)
    settings = Settings(_env_file=None)
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").json() == {"status": "ready"}
        with app.state.session_factory() as session:
            assert session.scalar(text("SELECT version_num FROM alembic_version")) == (
                ScriptDirectory.from_config(config).get_current_head()
            )
