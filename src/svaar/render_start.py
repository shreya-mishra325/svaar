"""Free Render startup: migrate before binding one restricted web process."""

import logging
import os
import re
import subprocess
import time

from sqlalchemy import text
from sqlalchemy.engine import make_url

from svaar.config import Settings
from svaar.db import create_database_engine
from svaar.logging import configure_logging

logger = logging.getLogger(__name__)
LOCK_KEY = 734929104


def render_hostname() -> str:
    """Fail closed outside the documented Render public-web-service boundary."""
    hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "")
    if (
        os.environ.get("RENDER") != "true"
        or os.environ.get("RENDER_SERVICE_TYPE") != "web"
        or re.fullmatch(r"[a-z0-9][a-z0-9-]*\.onrender\.com", hostname) is None
    ):
        raise ValueError("Render public web-service metadata required")
    return hostname


def normalized_database_url(value: str) -> str:
    """Accept Render's PostgreSQL URL without losing credentials or SSL options."""
    url = make_url(value)
    if url.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}:
        raise ValueError("PostgreSQL database required")
    return url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)


def migrate(settings: Settings) -> None:
    """Serialize overlapping cold starts; never print a credential-bearing traceback."""
    engine = create_database_engine(settings)
    try:
        with engine.connect() as connection:
            acquired = False
            try:
                for _ in range(30):
                    acquired = bool(
                        connection.scalar(
                            text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY}
                        )
                    )
                    connection.commit()
                    if acquired:
                        break
                    time.sleep(1)
                if not acquired:
                    raise RuntimeError("Migration lock unavailable")
                result = subprocess.run(
                    ["alembic", "upgrade", "head"],
                    capture_output=True,
                    timeout=120,
                    check=False,
                )
                if result.returncode:
                    raise RuntimeError("Database migration failed")
                logger.info("render_migrations_complete")
            finally:
                if acquired:
                    connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
                    connection.commit()
    finally:
        engine.dispose()


def main() -> int:
    """Use startup migrations on Free; no paid pre-deploy task or worker."""
    configure_logging("INFO")
    try:
        render_hostname()
        port = int(os.environ.get("PORT", "10000"))
        if not 1024 <= port <= 65535:
            raise ValueError("Invalid service port")
        os.environ["SVAAR_DATABASE_URL"] = normalized_database_url(os.environ["SVAAR_DATABASE_URL"])
        settings = Settings(_env_file=None)
        if settings.environment != "production":
            raise ValueError("Production mode required")
        if (
            settings.voice_turn_mode != "llm_endpoint"
            or settings.voice_status_secret is None
            or settings.voice_turn_token is None
        ):
            raise ValueError("Independent voice credentials and custom LLM mode required")
        migrate(settings)
    except Exception as exc:
        logger.error("render_start_failed", extra={"error_type": type(exc).__name__})
        return 1
    os.execvp(
        "uvicorn",
        [
            "uvicorn",
            "svaar.render_ingress:create_render_app",
            "--factory",
            "--host",
            "0.0.0.0",
            "--port",
            str(port),
            "--workers",
            "1",
            "--no-access-log",
            "--no-proxy-headers",
        ],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
