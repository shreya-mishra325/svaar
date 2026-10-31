"""Container probe that follows the configured port without exposing environment."""

import os
import urllib.request


def main() -> None:
    """Only inspect HTTP readiness; no provider requests or credential output."""
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "127.0.0.1")
    request = urllib.request.Request(f"http://127.0.0.1:{port}/ready", headers={"Host": host})
    with urllib.request.urlopen(request, timeout=4):
        pass


if __name__ == "__main__":
    main()
