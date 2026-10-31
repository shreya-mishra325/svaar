"""Scoped status claims and deterministic evidence; no model assigns truth."""

import hashlib
import re
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from svaar.identity.service import get_principal
from svaar.incidents.models import Claim, ClaimEvidence, IncidentEvent, ObservedEvent
from svaar.incidents.service import get_incident
from svaar.integrations.models import WebhookDelivery


class ClaimInput(BaseModel):
    """A caller's assertion; its fields are never evidence."""

    model_config = ConfigDict(extra="forbid")
    incident_id: uuid.UUID
    statement: str = Field(min_length=1, max_length=4000)
    kind: Literal["workflow_succeeded", "fix_merged"]
    run_id: int | None = Field(default=None, gt=0, le=9223372036854775807, strict=True)
    run_attempt: int | None = Field(default=None, gt=0, le=2147483647, strict=True)
    head_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{40,64}$")
    pull_number: int | None = Field(default=None, gt=0, le=2147483647, strict=True)

    @model_validator(mode="after")
    def validate_target(self):
        if not self.statement.strip():
            raise ValueError("A claim statement is required")
        if self.kind == "workflow_succeeded" and (self.run_id is None or self.run_attempt is None):
            raise ValueError("An exact workflow run and attempt are required")
        if self.kind == "fix_merged" and (self.run_id is not None or self.run_attempt is not None):
            raise ValueError("Merge claims do not use workflow success as evidence")
        if self.kind == "workflow_succeeded" and self.pull_number is not None:
            raise ValueError("Workflow claims do not use merge events as evidence")
        return self


class ClaimConflictError(Exception):
    """A trusted source key already belongs to different claim content."""


def record_claim(
    session: Session,
    org_id: uuid.UUID,
    author_id: uuid.UUID,
    body: ClaimInput,
    source_key: str,
) -> Claim:
    """Idempotently persist an assertion and check existing evidence; caller commits."""
    get_incident(session, org_id, body.incident_id)
    if get_principal(session, org_id, author_id) is None:
        raise ValueError("Claim author is unavailable")
    key = hashlib.sha256(f"{author_id}:{source_key}".encode()).hexdigest()
    lock = int.from_bytes(
        hashlib.sha256(f"claim:{org_id}:{key}".encode()).digest()[:8], "big", signed=True
    )
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
    claim = session.scalar(select(Claim).where(Claim.org_id == org_id, Claim.source_key == key))
    values = body.model_dump()
    if claim is not None:
        if any(getattr(claim, name) != value for name, value in values.items()):
            raise ClaimConflictError("Claim source conflicts with existing content")
    else:
        claim = Claim(org_id=org_id, author_id=author_id, source_key=key, **values)
        session.add(claim)
        session.flush()
    return check_claim(session, org_id, claim.id)


def check_claim(session: Session, org_id: uuid.UUID, claim_id: uuid.UUID) -> Claim:
    """Derive status only from persisted, scoped event evidence; never from absence."""
    claim = session.scalar(
        select(Claim)
        .where(
            Claim.org_id == org_id,
            Claim.id == claim_id,
        )
        .with_for_update()
    )
    if claim is None:
        raise LookupError("Claim not found")
    incident = get_incident(session, org_id, claim.incident_id)
    # Only a narrow positive workflow assertion can be confirmed by workflow facts.
    # A model-selected kind cannot turn "fix merged", a question or a compound
    # statement into a workflow-success assertion.
    positive_workflow = re.fullmatch(
        r"(?:(?:the|this|that)\s+)?(?:ci|workflow|pipeline|build|run|attempt)"
        r"(?:\s+(?:run|attempt))?(?:\s+(?P<run>[0-9]+))?\s+(?:has\s+)?"
        r"(?:passed|succeeded|is green|was successful|completed successfully)[.!]?",
        claim.statement.strip(),
        re.IGNORECASE,
    )
    if positive_workflow is not None and positive_workflow.group("run") is not None:
        if int(positive_workflow.group("run")) != claim.run_id:
            positive_workflow = None
    if claim.kind == "workflow_succeeded" and positive_workflow is not None:
        events = session.scalars(
            select(ObservedEvent)
            .join(IncidentEvent, IncidentEvent.event_id == ObservedEvent.id)
            .join(WebhookDelivery, WebhookDelivery.id == ObservedEvent.source_delivery_id)
            .where(
                IncidentEvent.incident_id == incident.id,
                ObservedEvent.org_id == org_id,
                ObservedEvent.repository_id == incident.repository_id,
                ObservedEvent.source == "github",
                ObservedEvent.kind == "workflow_run.completed",
                WebhookDelivery.event_id == ObservedEvent.id,
                WebhookDelivery.org_id == org_id,
                WebhookDelivery.state == "accepted",
            )
            .order_by(ObservedEvent.occurred_at, ObservedEvent.id)
        ).all()
        for event in events:
            data = event.data
            if (
                data.get("run_id") != claim.run_id
                or data.get("run_attempt") != claim.run_attempt
                or data.get("status") != "completed"
                or data.get("conclusion") != "success"
                or (claim.head_sha is not None and data.get("head_sha") != claim.head_sha)
            ):
                continue
            existing = session.scalar(
                select(ClaimEvidence.id).where(
                    ClaimEvidence.claim_id == claim.id,
                    ClaimEvidence.event_id == event.id,
                )
            )
            if existing is None:
                session.add(
                    ClaimEvidence(
                        org_id=org_id,
                        claim_id=claim.id,
                        event_id=event.id,
                        stance="supports",
                        rule="workflow-success-v1",
                    )
                )
    if claim.kind == "fix_merged" and claim.pull_number is not None:
        _merge_evidence(session, org_id, claim, incident)
    session.flush()
    stances = set(
        session.scalars(
            select(ClaimEvidence.stance).where(
                ClaimEvidence.claim_id == claim.id,
                ClaimEvidence.org_id == org_id,
            )
        )
    )
    claim.status = (
        "confirmed"
        if stances == {"supports"}
        else "contradicted"
        if stances == {"contradicts"}
        else "unverified"
    )
    session.flush()
    return claim


POSITIVE_MERGE = re.compile(
    r"(?:(?:the|this|that|my|our)\s+)?(?:fix|pr|pull request|change|patch)"
    r"(?:\s+#?(?P<pr>[0-9]+))?\s+(?:is|was|has been|got)\s+merged[.!]?",
    re.IGNORECASE,
)


def _merge_evidence(session: Session, org_id: uuid.UUID, claim: Claim, incident) -> None:
    """Support a narrow merge assertion only with a signed same-repository merge fact.

    The merge must name the claim's pull request and happen no earlier than the
    incident opened. Absent merges and unrecognized wording produce no evidence.
    """
    match = POSITIVE_MERGE.fullmatch(claim.statement.strip())
    if match is None or (
        match.group("pr") is not None and int(match.group("pr")) != claim.pull_number
    ):
        return
    events = session.scalars(
        select(ObservedEvent)
        .join(WebhookDelivery, WebhookDelivery.id == ObservedEvent.source_delivery_id)
        .where(
            ObservedEvent.org_id == org_id,
            ObservedEvent.repository_id == incident.repository_id,
            ObservedEvent.source == "github",
            ObservedEvent.kind == "pull_request.merged",
            ObservedEvent.occurred_at >= incident.opened_at,
            WebhookDelivery.event_id == ObservedEvent.id,
            WebhookDelivery.org_id == org_id,
            WebhookDelivery.state == "accepted",
        )
        .order_by(ObservedEvent.occurred_at, ObservedEvent.id)
    ).all()
    for event in events:
        if event.data.get("pull_number") != claim.pull_number:
            continue
        existing = session.scalar(
            select(ClaimEvidence.id).where(
                ClaimEvidence.claim_id == claim.id, ClaimEvidence.event_id == event.id
            )
        )
        if existing is None:
            session.add(
                ClaimEvidence(
                    org_id=org_id,
                    claim_id=claim.id,
                    event_id=event.id,
                    stance="supports",
                    rule="merge-event-v1",
                )
            )


def list_claims(session: Session, org_id: uuid.UUID, incident_id: uuid.UUID) -> list[Claim]:
    """Read claims only within the requested organization and incident."""
    get_incident(session, org_id, incident_id)
    return list(
        session.scalars(
            select(Claim)
            .where(
                Claim.org_id == org_id,
                Claim.incident_id == incident_id,
            )
            .order_by(Claim.created_at, Claim.id)
            .limit(100)
        )
    )


def claim_summary(session: Session, claim: Claim) -> dict:
    """Expose assertions separately from the evidence that supports their status."""
    evidence = session.scalars(
        select(ClaimEvidence)
        .where(
            ClaimEvidence.claim_id == claim.id,
            ClaimEvidence.org_id == claim.org_id,
        )
        .order_by(ClaimEvidence.created_at, ClaimEvidence.id)
    ).all()
    return {
        "claim_id": str(claim.id),
        "incident_id": str(claim.incident_id),
        "author_id": str(claim.author_id),
        "statement": claim.statement,
        "kind": claim.kind,
        "status": claim.status,
        "run_id": claim.run_id,
        "run_attempt": claim.run_attempt,
        "head_sha": claim.head_sha,
        "pull_number": claim.pull_number,
        "evidence": [
            {
                "event_id": str(row.event_id) if row.event_id else None,
                "claim_answer_id": str(row.claim_answer_id) if row.claim_answer_id else None,
                "stance": row.stance,
                "rule": row.rule,
            }
            for row in evidence
        ],
    }
