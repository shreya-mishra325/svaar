"""Gateway process entry point and infrastructure diagnostic.

The channel listener, outbox sender, and polling runtime are feature work. Normal
startup fails explicitly until that runtime is implemented; --check only verifies
configuration and database access and never claims that channels are connected.
"""

import argparse
import logging
from collections.abc import Sequence

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from svaar.config import Settings
from svaar.db import create_database_engine
from svaar.logging import configure_logging

logger = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    """Check gateway infrastructure or refuse an unavailable listener runtime."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Check settings and database, then exit"
    )
    arguments = parser.parse_args(argv)
    try:
        settings = Settings()
    except ValidationError:
        configure_logging("ERROR")
        logger.error("gateway_configuration_invalid; check SVAAR_ settings")
        return 2

    configure_logging(settings.log_level)
    if not arguments.check:
        logger.error(
            "gateway_runtime_unavailable; implement the channel listener, outbox sender, "
            "and jobs runtime before enabling this service; use --check for infrastructure only"
        )
        return 2

    engine = create_database_engine(settings)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.error("gateway_database_unavailable", extra={"error_type": type(exc).__name__})
        return 1
    finally:
        engine.dispose()

    logger.info("gateway_infrastructure_check_passed; channel runtime was not checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
