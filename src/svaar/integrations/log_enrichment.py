"""Explicit log enrichment outside webhook transactions; no scheduled/live calls."""

import hashlib
import re
import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from svaar.config import Settings
from svaar.incidents.fingerprints import ALGORITHM, MAX_FILES, failure_fingerprint
from svaar.incidents.models import ObservedEvent, WorkflowLogSignature
from svaar.integrations.github_app import GithubAppClient
from svaar.integrations.models import RepoMapping, WebhookDelivery


def enrich_event(
    sessions: sessionmaker[Session],
    settings: Settings,
    org_id: uuid.UUID,
    event_id: uuid.UUID,
) -> str:
    """Read verified attempt logs and persist only a scoped, append-only digest.

    Explicit internal invocation may make provider reads. No startup, route,
    model tool or worker invokes it automatically. Caller owns adapter failure
    policy; unavailable logs propagate sanitized errors without fabricating rows.
    """
    with sessions() as session:
        event = session.scalar(
            select(ObservedEvent).where(
                ObservedEvent.id == event_id,
                ObservedEvent.org_id == org_id,
            )
        )
        if event is None:
            return "not_found"
        receipt = session.get(WebhookDelivery, event.source_delivery_id)
        if (
            event.source != "github"
            or event.kind != "workflow_run.completed"
            or receipt is None
            or receipt.event_id != event.id
            or receipt.org_id != org_id
            or receipt.state != "accepted"
        ):
            return "unsupported"
        data = dict(event.data)
        if (
            data.get("status") != "completed"
            or data.get("conclusion") not in {"failure", "timed_out", "startup_failure"}
            or any(
                type(data.get(k)) is not int or data[k] <= 0
                for k in ("run_id", "run_attempt", "workflow_id")
            )
            or not isinstance(data.get("head_sha"), str)
            or re.fullmatch(r"[0-9a-f]{40,64}", data["head_sha"]) is None
            or not isinstance(data.get("head_branch"), str)
            or not 1 <= len(data["head_branch"]) <= 255
        ):
            return "unsupported"
        repository_id = event.repository_id
        mapping = session.scalar(
            select(RepoMapping).where(
                RepoMapping.repository_id == repository_id,
                RepoMapping.org_id == org_id,
            )
        )
        if mapping is None:
            return "unmapped"
        installation_id = mapping.installation_id
        provider = GithubAppClient.for_repository(session, settings, org_id, repository_id)

    # Never hold a DB transaction/row lock while signing or downloading logs.
    try:
        signature = provider.workflow_attempt_signature(
            data["run_id"],
            data["run_attempt"],
            head_sha=data["head_sha"],
            workflow_id=data["workflow_id"],
            branch=data["head_branch"],
        )
    finally:
        provider.close()
    if (
        signature.algorithm != ALGORITHM
        or type(signature.file_count) is not int
        or not 1 <= signature.file_count <= MAX_FILES
    ):
        raise ValueError("Unsupported log signature metadata")
    fingerprint = failure_fingerprint(
        org_id,
        repository_id,
        data["workflow_id"],
        data["head_branch"],
        signature,
    )
    scope = (
        f"log-signature:{org_id}:{repository_id}:{data['run_id']}:{data['run_attempt']}:{ALGORITHM}"
    )
    lock = int.from_bytes(hashlib.sha256(scope.encode()).digest()[:8], "big", signed=True)
    with sessions.begin() as session:
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
        mapping = session.scalar(
            select(RepoMapping)
            .where(
                RepoMapping.repository_id == repository_id,
                RepoMapping.org_id == org_id,
            )
            .with_for_update()
        )
        if mapping is None or mapping.installation_id != installation_id:
            return "mapping_changed"
        previous = session.scalar(
            select(WorkflowLogSignature).where(
                WorkflowLogSignature.org_id == org_id,
                WorkflowLogSignature.repository_id == repository_id,
                WorkflowLogSignature.run_id == data["run_id"],
                WorkflowLogSignature.run_attempt == data["run_attempt"],
                WorkflowLogSignature.algorithm == ALGORITHM,
            )
        )
        if previous is not None:
            if (
                previous.digest != signature.digest
                or previous.fingerprint != fingerprint
                or previous.head_sha != data["head_sha"]
                or previous.installation_id != installation_id
            ):
                return "conflict"
            return "duplicate"
        session.add(
            WorkflowLogSignature(
                event_id=event_id,
                org_id=org_id,
                repository_id=repository_id,
                installation_id=installation_id,
                run_id=data["run_id"],
                run_attempt=data["run_attempt"],
                workflow_id=data["workflow_id"],
                head_sha=data["head_sha"],
                head_branch=data["head_branch"],
                algorithm=signature.algorithm,
                digest=signature.digest,
                fingerprint=fingerprint,
                file_count=signature.file_count,
            )
        )
        return "recorded"
