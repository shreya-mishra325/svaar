"""Operator routes for incidents; chat and voice use the incident tools instead."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from svaar.api.auth import require_operator
from svaar.api.errors import ErrorResponse
from svaar.db import get_session
from svaar.incidents import claims, service
from svaar.incidents.models import Incident

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
