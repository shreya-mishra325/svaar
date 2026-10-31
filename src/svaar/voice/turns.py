"""Authenticated Bolna turn routes: the custom-LLM endpoint or the function bridge.

Only the route for SVAAR_VOICE_TURN_MODE is mounted. The bearer token is compared
in constant time and is the only credential; the private call reference is a
locator resolved by hash. Synchronous agent work runs off the event loop.

Contract (Bolna docs, checked 2026-10-31): a custom LLM receives OpenAI-style
chat completions at {base_url}/chat/completions with Bearer auth and must stream
OpenAI delta chunks ending in data: [DONE]. How the agent prompt and its
{{call_ref}} variable reach the request, and how Bolna retries, are unverified
until a live call; requests without the marker fail closed. Sources:
https://www.bolna.ai/docs/customizations/using-custom-llm
https://www.bolna.ai/docs/tool-calling/custom-function-calls
"""

import hmac
import json
import re
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from svaar.voice.runtime import REFUSAL

MAX_BODY_BYTES = 512 * 1024
# The Bolna agent prompt carries this line; Svaar is the LLM, so it is never spoken.
REFERENCE_MARKER = re.compile(r"svaar_call_ref:\s*([A-Za-z0-9_-]{43,128})")
MODEL_ID = "svaar"


class _Message(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    role: str = Field(min_length=1, max_length=32)
    content: str | list[Any] | None = None


class ChatRequest(BaseModel):
    """The OpenAI-compatible subset Svaar reads; other fields are ignored."""

    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    messages: list[_Message] = Field(min_length=1, max_length=1000)
    model: str = Field(default=MODEL_ID, max_length=200)
    stream: bool = False


class FunctionTurn(BaseModel):
    """The ask_svaar bridge parameters."""

    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    call_ref: str = Field(min_length=1, max_length=200, repr=False)
    utterance: str = Field(min_length=1, max_length=20000, repr=False)


def _text(content: str | list[Any] | None) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            part["text"]
            for part in content
            if isinstance(part, dict)
            and part.get("type") == "text"
            and isinstance(part.get("text"), str)
        )
    return ""


def parse_turn(messages: list[_Message]) -> tuple[str, str, int] | None:
    """Return (reference, caller text, zero-based turn index), or None to refuse.

    The index is the count of earlier caller messages in the replayed history, so a
    retried request for the same turn maps to the same saved reply.
    """
    references = {
        match.group(1)
        for message in messages
        if message.role == "system"
        for match in REFERENCE_MARKER.finditer(_text(message.content))
    }
    if len(references) != 1:
        return None
    if messages[-1].role != "user":
        return None
    users = [_text(message.content) for message in messages if message.role == "user"]
    text = users[-1].strip()
    if not text:
        return None
    return references.pop(), text, len(users) - 1


def _authorize(request: Request) -> None:
    token = request.app.state.settings.voice_turn_token
    if token is None:
        raise HTTPException(503)
    values = request.headers.getlist("authorization")
    expected = ("Bearer " + token.get_secret_value()).encode()
    if len(values) != 1 or not hmac.compare_digest(values[0].encode(), expected):
        raise HTTPException(401)


async def _json(request: Request) -> object:
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_BODY_BYTES:
            raise HTTPException(413)
        raw.extend(chunk)
    try:
        return json.loads(bytes(raw))
    except (ValueError, RecursionError):
        raise HTTPException(422) from None


def _runner(request: Request):
    runner = getattr(request.app.state, "voice_reference_runner", None)
    if runner is None:
        raise HTTPException(503)
    return runner


def _completion(reply: str, model: str, identifier: str, created: int) -> dict[str, Any]:
    return {
        "id": identifier,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": reply},
                "finish_reason": "stop",
            }
        ],
    }


def _chunk(identifier: str, created: int, model: str, delta: dict, finish: str | None) -> str:
    body = {
        "id": identifier,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return "data: " + json.dumps(body, separators=(",", ":")) + "\n\n"


llm_router = APIRouter(tags=["voice"])


@llm_router.get("/voice/llm/models")
async def list_models(request: Request) -> dict[str, Any]:
    """Optional Bolna key/model check at save time."""
    _authorize(request)
    return {"object": "list", "data": [{"id": MODEL_ID, "object": "model", "owned_by": "svaar"}]}


@llm_router.post("/voice/llm/chat/completions", response_model=None)
async def chat_completions(request: Request) -> JSONResponse | StreamingResponse:
    """Run one caller turn through the shared agent and reply in OpenAI format."""
    _authorize(request)
    runner = _runner(request)
    try:
        body = ChatRequest.model_validate(await _json(request))
    except ValidationError:
        raise HTTPException(422) from None
    turn = parse_turn(body.messages)
    identifier, created = "chatcmpl-" + uuid.uuid4().hex, int(time.time())

    async def reply() -> str:
        if turn is None:
            return REFUSAL
        reference, text, index = turn
        return await run_in_threadpool(runner.run_turn, reference, text, turn_index=index)

    if not body.stream:
        return JSONResponse(_completion(await reply(), body.model, identifier, created))

    async def events() -> AsyncIterator[str]:
        # The role chunk goes first so the connection is live while the turn runs.
        yield _chunk(identifier, created, body.model, {"role": "assistant"}, None)
        yield _chunk(identifier, created, body.model, {"content": await reply()}, None)
        yield _chunk(identifier, created, body.model, {}, "stop")
        yield "data: [DONE]\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


function_router = APIRouter(tags=["voice"])


@function_router.post("/voice/turn")
async def function_turn(request: Request) -> dict[str, str]:
    """ask_svaar bridge; Bolna supplies no retry identity, so arrivals are sequenced."""
    _authorize(request)
    runner = _runner(request)
    try:
        body = FunctionTurn.model_validate(await _json(request))
    except ValidationError:
        raise HTTPException(422) from None
    reply = await run_in_threadpool(runner.run_next, body.call_ref, body.utterance)
    return {"reply": reply}


def turn_router(mode: str) -> APIRouter:
    """Return only the router for the configured turn mode."""
    return llm_router if mode == "llm_endpoint" else function_router
