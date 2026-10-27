"""Opt-in CI log worker, separate from chat polling because downloads can be slow."""

import argparse
import logging
import signal
import threading
from collections.abc import Sequence

from pydantic import ValidationError
from sqlalchemy.orm import sessionmaker

from svaar.config import Settings
from svaar.db import create_database_engine
from svaar.integrations.log_enrichment import enrich_event
from svaar.jobs.ci import CiWorker
from svaar.logging import configure_logging

logger = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    """Poll persisted jobs with fake/real readers selected through composition."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Process one bounded batch")
    args = parser.parse_args(argv)
    try:
        settings = Settings()
    except ValidationError:
        return 2
    configure_logging(settings.log_level)
    if not settings.github_enrichment_enabled:
        logger.error("ci_worker_disabled; explicitly enable GitHub enrichment")
        return 2
    if settings.github_app_id is None or settings.github_private_key_b64 is None:
        logger.error("ci_worker_configuration_incomplete")
        return 2
    engine = create_database_engine(settings)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    worker = CiWorker(
        sessions,
        lambda org, event: enrich_event(sessions, settings, org, event),
        batch_size=settings.ci_batch_size,
    )
    stop = threading.Event()
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        for sig in previous:
            signal.signal(sig, lambda *_: stop.set())
        while not stop.is_set():
            try:
                worker.run_once()
            except Exception as exc:
                logger.error("ci_worker_tick_failed", extra={"error_type": type(exc).__name__})
                if args.once:
                    return 1
            if args.once or stop.wait(settings.ci_poll_seconds):
                break
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
