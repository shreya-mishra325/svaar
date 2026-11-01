"""Validate the single local .env; legacy explicit export never publishes or calls."""

import argparse
import json
import os
import secrets
from collections.abc import Sequence
from pathlib import Path

from dotenv import dotenv_values
from pydantic import ValidationError

from svaar.config import Settings

# Copy only known provider configuration. Never inherit development DB credentials
# or flags that can enable external writes.
PROVIDER_FIELDS = (
    "SVAAR_LLM_BASE_URL",
    "SVAAR_LLM_API_KEY",
    "SVAAR_LLM_MODEL",
    "SVAAR_CASPIAN_BASE_URL",
    "SVAAR_CASPIAN_API_KEY",
    "SVAAR_CASPIAN_TELEGRAM_CONNECTION_ID",
    "SVAAR_CASPIAN_TELEGRAM_ADDRESS",
    "SVAAR_BOLNA_API_KEY",
    "SVAAR_BOLNA_AGENT_ID",
    "SVAAR_GITHUB_APP_ID",
    "SVAAR_GITHUB_PRIVATE_KEY_B64",
    "SVAAR_GITHUB_WEBHOOK_SECRET",
)


def prepare(source: Path, destination: Path) -> None:
    """Create a private, exclusive demo environment without overwriting any file."""
    original = dotenv_values(source, interpolate=False)
    password = secrets.token_urlsafe(36)
    values = {key: original[key] for key in PROVIDER_FIELDS if original.get(key)}
    values.update(
        {
            "SVAAR_ENVIRONMENT": "production",
            "SVAAR_LOG_LEVEL": "INFO",
            "POSTGRES_USER": "svaar_demo",
            "POSTGRES_DB": "svaar_demo",
            "POSTGRES_PASSWORD": password,
            "SVAAR_DATABASE_URL": f"postgresql+psycopg://svaar_demo:{password}@db:5432/svaar_demo",
            "SVAAR_DATABASE_TIMEOUT_SECONDS": "5",
            "SVAAR_OPERATOR_TOKEN": secrets.token_urlsafe(36),
            "SVAAR_VOICE_STATUS_SECRET": secrets.token_urlsafe(36),
            "SVAAR_VOICE_TURN_TOKEN": secrets.token_urlsafe(36),
            "SVAAR_VOICE_TURN_MODE": "llm_endpoint",
            "SVAAR_CLASSIFIER_ENABLED": "true",
            "SVAAR_CHANNEL_TRANSPORT": "caspian",
            "SVAAR_GITHUB_ACTIONS_ENABLED": "false",
            "SVAAR_GITHUB_ENRICHMENT_ENABLED": "false",
            "SVAAR_ESCALATION_JOBS_ENABLED": "false",
            "SVAAR_CLAIM_CHECK_JOBS_ENABLED": "false",
            "SVAAR_ALLOW_SAME_CHANNEL_CONFIRMATION": "false",
            "CLOUDFLARE_TUNNEL_TOKEN": "",
        }
    )
    # An explicit export is also a self-contained CI fixture for compose.demo.yaml.
    # Keep the private fallback namespace aligned with the generated values, never
    # copy a source database password or Render credentials into that namespace.
    for name in (
        "POSTGRES_USER",
        "POSTGRES_DB",
        "POSTGRES_PASSWORD",
        "SVAAR_OPERATOR_TOKEN",
        "SVAAR_VOICE_STATUS_SECRET",
        "SVAAR_VOICE_TURN_TOKEN",
    ):
        values["SVAAR_DEMO_" + name.removeprefix("SVAAR_")] = values[name]
    # Compose understands single quoted dotenv values; literal newlines are valid.
    content = "# Private generated demo environment. Do not commit or print.\n"
    for key, value in values.items():
        content += key + "='" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'\n"
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(content)


def main(argv: Sequence[str] | None = None) -> int:
    """Validate .env by default; export only to an explicitly requested destination."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(".env"))
    parser.add_argument("--output", type=Path, help="Optional explicit legacy export destination")
    args = parser.parse_args(argv)
    if args.output is None:
        try:
            Settings(_env_file=args.source)
        except ValidationError:
            print(json.dumps({"valid": False, "reason": "configuration_invalid"}))
            return 1
        print(
            json.dumps({"valid": True, "configuration_file": str(args.source), "files_created": 0})
        )
        return 0
    try:
        prepare(args.source, args.output)
    except FileExistsError:
        print(json.dumps({"created": False, "reason": "destination_exists"}))
        return 1
    print(json.dumps({"created": True, "secrets_printed": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
