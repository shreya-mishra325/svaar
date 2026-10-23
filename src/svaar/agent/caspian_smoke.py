"""Read-only connection probe; sends no messages and does not advance a cursor."""

import json

from pydantic import ValidationError

from svaar.agent.caspian import CaspianTelegramTransport
from svaar.agent.transport import TransportUnavailableError
from svaar.config import Settings


def main() -> int:
    """Print only sanitized connectivity metadata; never identities or payloads."""
    adapter = None
    try:
        adapter = CaspianTelegramTransport.from_settings(Settings())
        adapter.check_connection()
        # Start at zero for schema verification only. No messages are processed.
        batch = adapter.poll(after_seq=0, limit=1)
        print(
            json.dumps(
                {
                    "connection_verified": True,
                    "poll_verified": True,
                    "private_text_messages_in_sample": len(batch.messages),
                    "sender_binding_policy": "caspian_address_mvp",
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
