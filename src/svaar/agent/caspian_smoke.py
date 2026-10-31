"""Read-only connection probe; sends no messages and does not advance a cursor."""

import argparse
import json
from collections.abc import Sequence

from pydantic import ValidationError

from svaar.agent.caspian import CaspianTransport
from svaar.agent.transport import TransportUnavailableError
from svaar.config import Settings


def main(argv: Sequence[str] | None = None) -> int:
    """Print only sanitized connectivity metadata; never identities or payloads."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", choices=("telegram", "slack", "discord", "email"))
    args = parser.parse_args(argv)
    adapter = None
    try:
        settings = Settings()
        if args.channel is not None:
            settings = settings.model_copy(update={"caspian_channel": args.channel})
        adapter = CaspianTransport.from_settings(settings)
        adapter.check_connection()
        # Start at zero for schema verification only. No messages are processed.
        batch = adapter.poll(after_seq=0, limit=1)
        print(
            json.dumps(
                {
                    "channel": settings.caspian_channel,
                    "connection_verified": True,
                    "privileged_runtime_available": settings.caspian_channel != "email",
                    "poll_verified": True,
                    "private_text_messages_in_sample": len(batch.messages),
                    "sender_binding_policy": (
                        "unverified_email_address"
                        if settings.caspian_channel == "email"
                        else "caspian_address_mvp"
                    ),
                    "stable_sender_id_verified": False,
                    "outbound_delivery_verified": False,
                    "messages_sent": 0,
                }
            )
        )
        return 0
    except (ValidationError, ValueError, TransportUnavailableError):
        print(json.dumps({"connection_verified": False, "messages_sent": 0}))
        return 1
    finally:
        if adapter is not None:
            adapter.close()


if __name__ == "__main__":
    raise SystemExit(main())
