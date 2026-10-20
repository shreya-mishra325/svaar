"""Operator routes for organizations and invites."""

import uuid
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from svaar.api.auth import require_operator
from svaar.api.errors import ErrorResponse
from svaar.db import get_session
from svaar.identity import service
from svaar.identity.models import Role

SessionDep = Annotated[Session, Depends(get_session)]

router = APIRouter(
    tags=["identity"],
    dependencies=[Depends(require_operator)],
    responses={401: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)


class OrgCreate(BaseModel):
    """Request to create an organization."""

    name: str = Field(min_length=1, max_length=200)


class OrgCreated(BaseModel):
    """Created organization."""

    id: uuid.UUID
    name: str


class InviteCreate(BaseModel):
    """Request to issue a single-use invite."""

    org_id: uuid.UUID
    role: Role


class InviteCreated(BaseModel):
    """Issued invite; the code is shown only in this response."""

    id: uuid.UUID
    org_id: uuid.UUID
    role: Role
    code: str
    expires_at: datetime


@router.post("/orgs", status_code=status.HTTP_201_CREATED, response_model=OrgCreated)
def create_org(body: OrgCreate, session: SessionDep) -> OrgCreated:
    """Create an organization."""
    org = service.create_org(session, body.name)
    session.commit()
    return OrgCreated(id=org.id, name=org.name)


@router.post(
    "/invites",
    status_code=status.HTTP_201_CREATED,
    response_model=InviteCreated,
    responses={404: {"model": ErrorResponse}},
)
def create_invite(body: InviteCreate, request: Request, session: SessionDep) -> InviteCreated:
    """Issue a single-use invite for a role in an existing organization."""
    ttl = timedelta(hours=request.app.state.settings.invite_ttl_hours)
    try:
        issued = service.create_invite(session, body.org_id, body.role, ttl)
    except service.IdentityError:
        raise HTTPException(404) from None
    session.commit()
    return InviteCreated(
        id=issued.invite.id,
        org_id=issued.invite.org_id,
        role=Role(issued.invite.role),
        code=issued.code,
        expires_at=issued.invite.expires_at,
    )
