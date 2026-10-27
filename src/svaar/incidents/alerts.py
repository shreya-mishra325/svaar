"""Who hears about a newly opened incident, and what they are told.

Delivery belongs to the agent outbox; this module only chooses recipients from the
incident's own organization and writes a short, secret-free message.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from svaar.identity.service import get_principal
from svaar.incidents.models import Incident


@dataclass(frozen=True)
class Alert:
    """One idempotent message for one principal."""

    principal_id: uuid.UUID
    key: str
    body: str


def opened_alerts(session: Session, incident: Incident) -> list[Alert]:
    """Notify only the explicit incident owner, rechecking organization scope."""
    owner = incident.owner_principal_id
    if owner is None or get_principal(session, incident.org_id, owner) is None:
        return []
    return [
        Alert(
            principal_id=owner,
            key=f"incident-opened:{incident.id}:{owner}",
            body=opened_message(incident),
        )
    ]


def opened_message(incident: Incident) -> str:
    """Describe the failure from recorded fields only; no logs, names or secrets."""
    workflow = incident.workflow_name or "A CI workflow"
    branch = f" on {incident.head_branch}" if incident.head_branch else ""
    return (
        f"CI failure: {workflow}{branch} failed. "
        "Ask me for the timeline to see what happened, or tell me to acknowledge it "
        "so escalation can stop."
    )
