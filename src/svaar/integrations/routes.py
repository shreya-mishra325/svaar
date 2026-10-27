"""Bounded, raw-body authenticated GitHub ingress and operator-owned repo mappings."""

import hashlib
import hmac
import logging
import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from svaar.api.auth import require_operator
from svaar.db import get_session
from svaar.identity.service import get_org, get_principal
from svaar.incidents.models import Incident
from svaar.integrations.github import (
    DeliveryConflictError,
    GithubJsonError,
    GithubPayloadError,
    ingest_delivery,
    queue_opened_alerts,
)
from svaar.integrations.models import RepoMapping

logger = logging.getLogger(__name__)
router = APIRouter(tags=["github"])
MAX_BODY_BYTES = 1024 * 1024


class RepoMappingCreate(BaseModel):
    """Explicit operator-approved repository, installation and organization."""

    model_config = ConfigDict(extra="forbid")
    repository_id: int = Field(gt=0, le=9223372036854775807, strict=True)
    installation_id: int = Field(gt=0, le=9223372036854775807, strict=True)
    org_id: uuid.UUID
    owner_principal_id: uuid.UUID | None = None


@router.post("/repo-mappings", status_code=201, dependencies=[Depends(require_operator)])
def create_repo_mapping(
    body: RepoMappingCreate,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    """Create once; remapping requires a separate reviewed migration/workflow."""
    if get_org(session, body.org_id) is None:
        raise HTTPException(404)
    if (
        body.owner_principal_id is not None
        and get_principal(session, body.org_id, body.owner_principal_id) is None
    ):
        raise HTTPException(404)
    session.add(RepoMapping(**body.model_dump()))
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409) from None
    return {
        "repository_id": body.repository_id,
        "installation_id": body.installation_id,
        "org_id": str(body.org_id),
        "owner_principal_id": str(body.owner_principal_id) if body.owner_principal_id else None,
    }


class RepoOwnerUpdate(BaseModel):
    """Operator-selected repository owner; optional assignment to open unowned incidents."""

    model_config = ConfigDict(extra="forbid")
    org_id: uuid.UUID
    owner_principal_id: uuid.UUID
    assign_unowned_incidents: bool = False


@router.put("/repo-mappings/{repository_id}/owner", dependencies=[Depends(require_operator)])
def set_repository_owner(
    repository_id: int,
    body: RepoOwnerUpdate,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    """Set future ownership; existing assigned/acknowledged incidents never transfer."""
    mapping = session.scalar(
        select(RepoMapping)
        .where(
            RepoMapping.repository_id == repository_id,
            RepoMapping.org_id == body.org_id,
        )
        .with_for_update()
    )
    if mapping is None or get_principal(session, body.org_id, body.owner_principal_id) is None:
        raise HTTPException(404)
    mapping.owner_principal_id = body.owner_principal_id
    assigned = 0
    if body.assign_unowned_incidents:
        incidents = session.scalars(
            select(Incident)
            .where(
                Incident.org_id == body.org_id,
                Incident.repository_id == repository_id,
                Incident.owner_principal_id.is_(None),
                Incident.state == "open",
            )
            .order_by(Incident.id)
            .with_for_update()
        ).all()
        for incident in incidents:
            incident.owner_principal_id = body.owner_principal_id
            queue_opened_alerts(session, incident)
            assigned += 1
    session.commit()
    return {
        "repository_id": repository_id,
        "owner_principal_id": str(body.owner_principal_id),
        "assigned_incidents": assigned,
    }


@router.post("/webhooks/github")
async def github_webhook(request: Request) -> JSONResponse:
    """Validate the exact bytes before JSON parsing; offload all synchronous DB work."""
    secret = request.app.state.settings.github_webhook_secret
    if secret is None:
        raise HTTPException(503)
    names = ("x-hub-signature-256", "x-github-delivery", "x-github-event")
    if any(len(request.headers.getlist(name)) != 1 for name in names):
        raise HTTPException(401)
    signature = request.headers["x-hub-signature-256"]
    if not re.fullmatch(r"sha256=[0-9a-f]{64}", signature):
        raise HTTPException(401)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BODY_BYTES:
            raise HTTPException(413)
        body.extend(chunk)
    raw = bytes(body)
    expected = (
        "sha256=" + hmac.new(secret.get_secret_value().encode(), raw, hashlib.sha256).hexdigest()
    )
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(401)
    try:
        delivery_id = uuid.UUID(request.headers["x-github-delivery"])
    except ValueError:
        raise HTTPException(422) from None
    event_type = request.headers["x-github-event"]
    if not re.fullmatch(r"[a-z_]{1,64}", event_type):
        raise HTTPException(422)
    try:
        status = await run_in_threadpool(
            ingest_delivery,
            request.app.state.session_factory,
            delivery_id,
            event_type,
            raw,
        )
    except GithubJsonError:
        raise HTTPException(400) from None
    except GithubPayloadError:
        raise HTTPException(422) from None
    except DeliveryConflictError:
        raise HTTPException(409) from None
    if status == "unmapped":
        logger.warning("github_repository_unmapped")
        raise HTTPException(404)
    if status == "ignored":
        return JSONResponse({"handled": False})
    return JSONResponse({"handled": True, "status": status})
