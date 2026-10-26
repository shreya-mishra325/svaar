"""Authenticated execution receipts only; no transcripts or claim inference."""

import hashlib
import hmac
import json
import uuid
from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from svaar.voice.calls import apply_provider_status
from svaar.voice.models import VoiceCall, VoiceWebhookEvent

router = APIRouter(tags=["voice"])
# Official Bolna webhook documentation, checked 2026-10-24.
ALLOWED_IPS = frozenset({"13.203.39.153", "13.126.9.249", "13.202.133.53"})
HEADER = "x-svaar-voice-status-secret"
MAX_BODY_BYTES = 1024 * 1024
FAILED_CALL_STATUSES = frozenset({"no-answer", "busy", "failed", "canceled", "stopped", "error"})
FailureNotifier = Callable[[Session, uuid.UUID, uuid.UUID, uuid.UUID], bool]


class StatusPayload(BaseModel):
    """Only receipt metadata is used; provider transcripts are discarded."""

    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    id: uuid.UUID
    agent_id: uuid.UUID
    status: str = Field(min_length=1, max_length=32)


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def ingest_status(
    sessions: sessionmaker[Session],
    body: StatusPayload,
    raw: bytes,
    notify_failure: FailureNotifier | None = None,
) -> str:
    """Serialize receipts on the known call, atomically with lifecycle updates."""
    with sessions() as session:
        call = session.scalar(
            select(VoiceCall).where(VoiceCall.execution_id == body.id).with_for_update()
        )
        if call is None or call.provider_agent_id != body.agent_id:
            return "not_found"
        previous = session.scalar(
            select(VoiceWebhookEvent.id).where(
                VoiceWebhookEvent.execution_id == body.id,
                VoiceWebhookEvent.status == body.status,
            )
        )
        if previous is not None:
            return "duplicate"
        session.add(
            VoiceWebhookEvent(
                voice_call_id=call.id,
                execution_id=body.id,
                status=body.status,
                payload_hash=hashlib.sha256(raw).hexdigest(),
            )
        )
        applied = apply_provider_status(call, body.status)
        if applied and body.status in FAILED_CALL_STATUSES and notify_failure is not None:
            # One transaction: a failed enqueue rolls back the receipt for safe redelivery.
            # False means no unambiguous verified private route; never invent a recipient.
            notify_failure(session, call.org_id, call.principal_id, call.id)
        session.commit()
        return "recorded" if applied else "ignored"


@router.post("/voice/status")
async def voice_status(request: Request) -> dict[str, str]:
    """Require a secret and an allowed IP through the selected ingress boundary."""
    secret = request.app.state.settings.voice_status_secret
    if secret is None:
        raise HTTPException(503)
    values = request.headers.getlist(HEADER)
    if len(values) != 1 or not hmac.compare_digest(
        values[0].encode(), secret.get_secret_value().encode()
    ):
        raise HTTPException(401)
    # Only the dedicated loopback Cloudflare listener trusts this edge header.
    # The normal application still checks the actual peer and ignores all headers.
    if getattr(request.app.state, "cloudflare_status_ingress", False):
        if request.client is None or request.client.host != "127.0.0.1":
            raise HTTPException(403)
        addresses = request.headers.getlist("cf-connecting-ip")
        if len(addresses) != 1 or addresses[0] not in ALLOWED_IPS:
            raise HTTPException(403)
    elif request.client is None or request.client.host not in ALLOWED_IPS:
        raise HTTPException(403)
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_BODY_BYTES:
            raise HTTPException(413)
        raw.extend(chunk)
    try:
        payload = StatusPayload.model_validate(
            json.loads(bytes(raw), object_pairs_hook=_unique_keys)
        )
    except (ValueError, ValidationError, RecursionError):
        raise HTTPException(422) from None
    result = await run_in_threadpool(
        ingest_status,
        request.app.state.session_factory,
        payload,
        bytes(raw),
        request.app.state.voice_failure_notifier,
    )
    if result == "not_found":
        raise HTTPException(404)
    return {"status": result}
