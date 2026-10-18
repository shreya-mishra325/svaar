"""Central JSON logging with deliberately limited diagnostic fields."""

import json
import logging
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    """Format events without serializing exception objects or arbitrary extras."""

    def format(self, record: logging.LogRecord) -> str:
        """Return one JSON object per log record."""
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if error_type := getattr(record, "error_type", None):
            payload["error_type"] = error_type
        return json.dumps(payload)


def configure_logging(level: str) -> None:
    """Configure application/server logs and suppress verbose provider diagnostics."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("httpx", "httpcore", "sqlalchemy.engine", "sqlalchemy.pool"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
