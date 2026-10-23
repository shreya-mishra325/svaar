"""Explicit GET-only Bolna readiness probe; never place calls or modify agents."""

import json
from dataclasses import asdict

from pydantic import ValidationError

from svaar.config import Settings
from svaar.voice.bolna import BolnaClient
from svaar.voice.provider import VoiceProviderUnavailableError


def main() -> int:
    """Print sanitized flags only; account readiness is not voice acceptance."""
    provider = None
    try:
        provider = BolnaClient.from_settings(Settings())
        result = provider.readiness()
        print(
            json.dumps(
                {
                    **asdict(result),
                    "account_agent_ready": result.ready,
                    "calls_placed": 0,
                    "measurement": "read_only_account_and_agent",
                }
            )
        )
        return 0 if result.ready else 1
    except (ValueError, ValidationError, VoiceProviderUnavailableError):
        print(json.dumps({"error": "bolna_readiness_unavailable_or_failed", "calls_placed": 0}))
        return 1
    finally:
        if provider is not None:
            provider.close()


if __name__ == "__main__":
    raise SystemExit(main())
