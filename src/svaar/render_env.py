"""Validate Render model/voice fields in .env without generating or rotating secrets."""

import json

from pydantic import ValidationError

from svaar.config import Settings


def main() -> int:
    """Read the single local configuration; never create another dotenv file."""
    try:
        settings = Settings()
    except ValidationError:
        print(json.dumps({"valid": False, "reason": "configuration_invalid"}))
        return 1
    if not all((settings.llm_model, settings.voice_turn_token, settings.voice_status_secret)):
        print(json.dumps({"valid": False, "reason": "model_or_voice_configuration_missing"}))
        return 1
    print(
        json.dumps(
            {
                "valid": True,
                "configuration_file": ".env",
                "files_created": 0,
                "credentials_rotated": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
