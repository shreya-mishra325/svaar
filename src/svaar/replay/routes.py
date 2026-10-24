"""Operator replay route; every response is labelled as a simulation."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from svaar.api.auth import require_operator
from svaar.api.errors import ErrorResponse
from svaar.db import get_session
from svaar.incidents.models import Incident
from svaar.replay import service
from svaar.replay.simulator import Scenario

router = APIRouter(
    tags=["replay"],
    dependencies=[Depends(require_operator)],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)


class ReplayOut(BaseModel):
    """A stored simulation."""

    id: uuid.UUID
    incident_id: uuid.UUID
    kind: str
    result: dict[str, Any]
    created_at: datetime


@router.post(
    "/incidents/{incident_id}/replay",
    status_code=status.HTTP_201_CREATED,
    response_model=ReplayOut,
)
def replay_incident(
    incident_id: uuid.UUID,
    scenario: Scenario,
    session: Annotated[Session, Depends(get_session)],
) -> ReplayOut:
    """Simulate a corrected pipeline for an incident; nothing real runs."""
    incident = session.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(404)
    run = service.run_replay(session, incident.org_id, incident.id, scenario)
    session.commit()
    return ReplayOut.model_validate(run, from_attributes=True)
