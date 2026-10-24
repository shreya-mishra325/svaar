"""Run a replay against an incident and store it as a simulation.

Only the fake simulator is used. Nothing here imports provider adapters or writes
observed events, and the incident itself is never changed by a replay.
"""

import uuid
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from svaar.incidents.service import get_incident
from svaar.replay.models import ReplayRun
from svaar.replay.simulator import SIMULATED, Scenario, simulate


def run_replay(
    session: Session, org_id: uuid.UUID, incident_id: uuid.UUID, scenario: Scenario
) -> ReplayRun:
    """Simulate the corrected pipeline for an incident in the organization."""
    get_incident(session, org_id, incident_id)
    simulation = simulate(scenario)
    run = ReplayRun(
        org_id=org_id,
        incident_id=incident_id,
        kind=SIMULATED,
        scenario=scenario.model_dump(mode="json"),
        result=asdict(simulation),
    )
    session.add(run)
    session.flush()
    return run


def list_replays(session: Session, org_id: uuid.UUID, incident_id: uuid.UUID) -> list[ReplayRun]:
    """Return an incident's replays, newest first."""
    get_incident(session, org_id, incident_id)
    return list(
        session.scalars(
            select(ReplayRun)
            .where(ReplayRun.org_id == org_id, ReplayRun.incident_id == incident_id)
            .order_by(ReplayRun.created_at.desc(), ReplayRun.id)
        )
    )
