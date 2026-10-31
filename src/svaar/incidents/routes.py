"""Operator routes for incidents; chat and voice use the incident tools instead."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from svaar.api.auth import require_operator
from svaar.api.errors import ErrorResponse
from svaar.db import get_session
from svaar.identity.service import get_org, get_principal
from svaar.incidents import claims, service
from svaar.incidents.models import Incident
from svaar.integrations.github import queue_opened_alerts
from svaar.integrations.models import RepoMapping

router = APIRouter(
    tags=["incidents"],
    dependencies=[Depends(require_operator)],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)


class IncidentOut(BaseModel):
    """Incident summary."""

    id: uuid.UUID
    org_id: uuid.UUID
    owner_principal_id: uuid.UUID | None
    repository_id: int
    state: str
    workflow_name: str | None
    head_branch: str | None
    failure_count: int
    opened_at: datetime
    last_failure_at: datetime
    acknowledged_at: datetime | None


class IncidentCreate(BaseModel):
    """An operator-reported incident for an explicitly mapped repository."""

    model_config = ConfigDict(extra="forbid")
    org_id: uuid.UUID
    repository_id: int = Field(gt=0, le=9223372036854775807, strict=True)
    workflow_id: int | None = Field(default=None, gt=0, le=9223372036854775807, strict=True)
    workflow_name: str | None = Field(default=None, min_length=1, max_length=200)
    head_branch: str | None = Field(default=None, min_length=1, max_length=255)
    owner_principal_id: uuid.UUID | None = None


class TimelineEntryOut(BaseModel):
    """One recorded fact."""

    occurred_at: datetime
    source: str
    kind: str
    run_id: int | None
    run_attempt: int | None
    status: str | None
    conclusion: str | None


class TimelineOut(BaseModel):
    """Incident and its events in occurrence order."""

    incident: IncidentOut
    events: list[TimelineEntryOut]


@router.post(
    "/incidents",
    status_code=201,
    response_model=IncidentOut,
    responses={409: {"model": ErrorResponse}},
)
def create_incident(
    body: IncidentCreate, session: Annotated[Session, Depends(get_session)]
) -> IncidentOut:
    """Open an incident manually; the owner defaults to the repository mapping's owner."""
    mapping = session.scalar(
        select(RepoMapping).where(
            RepoMapping.repository_id == body.repository_id,
            RepoMapping.org_id == body.org_id,
        )
    )
    if get_org(session, body.org_id) is None or mapping is None:
        raise HTTPException(404)
    owner = body.owner_principal_id or mapping.owner_principal_id
    if owner is not None and get_principal(session, body.org_id, owner) is None:
        raise HTTPException(404)
    try:
        incident = service.open_manual_incident(
            session,
            org_id=body.org_id,
            repository_id=body.repository_id,
            workflow_id=body.workflow_id,
            workflow_name=body.workflow_name,
            head_branch=body.head_branch,
            owner_principal_id=owner,
            now=datetime.now(UTC),
        )
    except service.ActiveIncidentExistsError:
        session.rollback()
        raise HTTPException(409) from None
    # The owner alert is queued atomically with the incident, exactly as for CI failures.
    queue_opened_alerts(session, incident)
    session.commit()
    return IncidentOut.model_validate(incident, from_attributes=True)


@router.get("/incidents/{incident_id}/timeline", response_model=TimelineOut)
def incident_timeline(
    incident_id: uuid.UUID, session: Annotated[Session, Depends(get_session)]
) -> TimelineOut:
    """Return an incident's observed events in order; the operator may read any organization."""
    incident = session.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(404)
    entries = service.timeline(session, incident.org_id, incident.id)
    return TimelineOut(
        incident=IncidentOut.model_validate(incident, from_attributes=True),
        events=[TimelineEntryOut.model_validate(entry, from_attributes=True) for entry in entries],
    )


@router.get("/incidents/{incident_id}/claims")
def incident_claims(
    incident_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    """Operator read-only view; no status refresh or provider request on GET."""
    incident = session.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(404)
    rows = claims.list_claims(session, incident.org_id, incident.id)
    return {"claims": [claims.claim_summary(session, row) for row in rows]}
