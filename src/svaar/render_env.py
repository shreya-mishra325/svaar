"""Prepare only Render model/voice secrets locally; never copy a development DB URL."""

import os
import secrets

from dotenv import dotenv_values


def main() -> None:
    """Create a private import file without overwriting local configuration."""
    source = dotenv_values(".env.demo", interpolate=False)
    fields = {
        name: source[name]
        for name in (
            "SVAAR_LLM_BASE_URL",
            "SVAAR_LLM_MODEL",
            "SVAAR_LLM_API_KEY",
        )
        if source.get(name)
    }
    fields.update(
        SVAAR_VOICE_TURN_TOKEN=secrets.token_urlsafe(36),
        SVAAR_VOICE_STATUS_SECRET=secrets.token_urlsafe(36),
    )
    descriptor = os.open(".env.render", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        for name, value in fields.items():
            stream.write(name + "='" + str(value).replace("'", "\\'") + "'\n")
    print("Render secret import file created privately; no values printed.")


if __name__ == "__main__":
    main()
