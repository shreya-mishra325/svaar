"""Structured logging excludes raw exception diagnostics and arbitrary extras."""

import json
import logging

from svaar.logging import JsonFormatter


def test_json_formatter_limits_fields() -> None:
    record = logging.LogRecord("svaar.test", logging.ERROR, __file__, 1, "request_failed", (), None)
    record.error_type = "RuntimeError"
    record.secret = "private-password"
    record.exc_info = (RuntimeError, RuntimeError("private-password"), None)
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "request_failed"
    assert payload["error_type"] == "RuntimeError"
    assert "private-password" not in json.dumps(payload)
