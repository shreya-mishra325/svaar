"""Local demo preparation; no publishing, messages or calls."""

import argparse
import json
import os
import secrets
from pathlib import Path

from dotenv import dotenv_values

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
    # Compose understands single quoted dotenv values; literal newlines are valid.
    content = "# Private generated demo environment. Do not commit or print.\n"
    for key, value in values.items():
        content += key + "='" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'\n"
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(content)


def main() -> int:
    """Prepare private demo settings without displaying credentials."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(".env"))
    parser.add_argument("--output", type=Path, default=Path(".env.demo"))
    args = parser.parse_args()
    try:
        prepare(args.source, args.output)
    except FileExistsError:
        print(json.dumps({"created": False, "reason": "destination_exists"}))
        return 1
    print(json.dumps({"created": True, "secrets_printed": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
