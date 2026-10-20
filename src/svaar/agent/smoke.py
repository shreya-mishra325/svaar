"""Manually invoked, inference-only native-tool probe; never execute proposed tools.

This command sends three real model requests when run by an operator. Automated
tests inject fake models. No prompts, credentials or provider payloads are printed.
"""

import json
from statistics import median
from time import monotonic

from pydantic import ValidationError

from svaar.agent.llm import ChatModel, HttpChatModel, ModelUnavailableError
from svaar.config import Settings
from svaar.logging import configure_logging


def check_native_tools(model: ChatModel) -> dict[str, object]:
    """Require three native calls with exact arguments and report non-streaming seconds."""
    latencies = []
    for index in range(3):
        expected = f"svaar-smoke-{index}"
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "smoke_echo",
                    "description": "Return the exact value requested in the message.",
                    "parameters": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                        "additionalProperties": False,
                    },
                },
            }
        ]
        start = monotonic()
        reply = model.complete(
            [
                {
                    "role": "user",
                    "content": f"Call smoke_echo with value {expected}. Use native tools.",
                }
            ],
            tools,
            timeout=6.0,
        )
        latencies.append(monotonic() - start)
        if (
            not reply.native_tools
            or len(reply.tools) != 1
            or reply.tools[0].name != "smoke_echo"
            or reply.tools[0].arguments != {"value": expected}
        ):
            raise ModelUnavailableError("Native tool probe failed")
    return {
        "requests": 3,
        "native_tool_calls": True,
        "median_response_seconds": round(median(latencies), 4),
        "measurement": "non_streaming_full_response_not_first_token",
    }


def main() -> int:
    """Load operator-provided model settings and print only redacted probe results."""
    model = None
    try:
        settings = Settings()
        configure_logging(settings.log_level)
        model = HttpChatModel.from_settings(settings)
        print(json.dumps(check_native_tools(model)))
    except (ValidationError, ModelUnavailableError):
        print(json.dumps({"error": "native_tool_probe_unavailable_or_failed"}))
        return 1
    finally:
        if model is not None:
            model.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
