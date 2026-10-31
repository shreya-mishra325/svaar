"""Process-local CI heartbeat, not a claim of external provider acceptance."""

import json
import os
import time
from pathlib import Path

PATH = Path("/tmp/svaar-ci-heartbeat.json")


def record(state: str, *, path: Path = PATH) -> None:
    """Replace heartbeat atomically; no identity, message or secret data."""
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps({"state": state, "at": time.time()}))
    temporary.replace(path)


def healthy(max_age: float, *, path: Path = PATH) -> bool:
    """Fail closed on absent, stale, future or malformed heartbeats."""
    try:
        data = json.loads(path.read_text())
        age = time.time() - data["at"]
        return data["state"] in {"running", "ready"} and 0 <= age <= max_age
    except (OSError, ValueError, KeyError, TypeError):
        return False
