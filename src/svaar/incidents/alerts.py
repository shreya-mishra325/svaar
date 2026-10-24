"""Who hears about a newly opened incident, and what they are told.

Delivery belongs to the agent outbox; this module only chooses recipients from the
incident's own organization and writes a short, secret-free message.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from svaar.identity.models import Principal, Role
from svaar.incidents.models import Incident

# No repository owner exists in the data model yet; these roles stand in for it.
ALERT_ROLES = frozenset({Role.OPS, Role.LEAD, Role.ADMIN})


@dataclass(frozen=True)
class Alert:
    """One idempotent message for one principal."""

    principal_id: uuid.UUID
    key: str
    body: str


def opened_alerts(session: Session, incident: Incident) -> list[Alert]:
    """Return one alert per eligible principal in the incident's organization."""
    principals = session.scalars(
        select(Principal.id)
        .where(
            Principal.org_id == incident.org_id,
            Principal.role.in_([role.value for role in ALERT_ROLES]),
        )
        .order_by(Principal.created_at, Principal.id)
    )
    body = opened_message(incident)
    return [
        Alert(principal_id=pid, key=f"incident-opened:{incident.id}:{pid}", body=body)
        for pid in principals
    ]


def opened_message(incident: Incident) -> str:
    """Describe the failure from recorded fields only; no logs, names or secrets."""
    workflow = incident.workflow_name or "A CI workflow"
    branch = f" on {incident.head_branch}" if incident.head_branch else ""
    return (
        f"CI failure: {workflow}{branch} failed. "
        "Ask me for the timeline to see what happened, or tell me to acknowledge it "
        "to take ownership."
    )
