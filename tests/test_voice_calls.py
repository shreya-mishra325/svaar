"""Durable placement and reconciliation with fake providers and real PostgreSQL."""

import hashlib
import threading
import uuid

import pytest
from factories import make_org, make_principal
from sqlalchemy import select

from svaar.identity.models import ChannelBinding
from svaar.voice.calls import CallService
from svaar.voice.models import VoiceCall
from svaar.voice.provider import (
    CallOutcomeUnknownError,
    CallReceipt,
    CallRejectedError,
    ExecutionStatus,
    VoiceProviderUnavailableError,
)


class Provider:
    agent_id = uuid.UUID("123e4567-e89b-12d3-a456-426655440000")

    def __init__(self):
        self.placements = []
        self.reads = []
        self.error = None
        self.status = "in-progress"
        self.identifier = uuid.uuid4()

    def place_call(self, phone, reference):
        self.placements.append((phone, reference))
        if self.error:
            raise self.error
        return CallReceipt(self.identifier)

    def execution(self, execution_id):
        self.reads.append(execution_id)
        if self.error:
            raise self.error
        return ExecutionStatus(execution_id, self.agent_id, self.status)


@pytest.fixture
def intent(session_factory):
    with session_factory() as session:
        org = make_org(session)
        principal = make_principal(session, org, bindings=(("phone", "+15555550123"),))
        binding = session.scalar(select(ChannelBinding))
        call = VoiceCall(
            org_id=org.id,
            principal_id=principal.id,
            phone_binding_id=binding.id,
            mission="escalation",
        )
        session.add(call)
        session.commit()
        return org.id, call.id


def test_claim_once_reference_is_hashed_and_status_is_not_answer_proof(session_factory, intent):
    provider = Provider()
    service = CallService(session_factory, provider)
    assert service.place(*intent) == "queued"
    assert service.place(*intent) == "queued"
    assert len(provider.placements) == 1
    with session_factory() as session:
        call = session.get(VoiceCall, intent[1])
        assert call.call_ref_hash == hashlib.sha256(provider.placements[0][1].encode()).hexdigest()
        assert call.execution_id == provider.identifier
        assert call.state == "queued" and call.provider_status == "queued"
    assert service.refresh(*intent) == "active"
    provider.status = "ringing"
    assert service.refresh(*intent) == "active"
    provider.status = "call-disconnected"
    assert service.refresh(*intent) == "queued"
    provider.status = "completed"
    assert service.refresh(*intent) == "closed"
    reads = len(provider.reads)
    provider.status = "in-progress"
    assert service.refresh(*intent) == "closed"
    assert len(provider.reads) == reads


@pytest.mark.parametrize(
    "failure, expected",
    [
        (CallRejectedError("private"), "failed"),
        (CallOutcomeUnknownError("private"), "reconciliation_required"),
        (RuntimeError("private"), "reconciliation_required"),
    ],
)
def test_failed_or_uncertain_placement_never_redials(session_factory, intent, failure, expected):
    provider = Provider()
    provider.error = failure
    service = CallService(session_factory, provider)
    assert service.place(*intent) == expected
    assert service.place(*intent) == expected
    assert len(provider.placements) == 1


@pytest.mark.parametrize("change", ["org", "unverified", "owner", "channel", "phone"])
def test_recipient_scope_rechecked_before_placement(session_factory, intent, change):
    org, identifier = intent
    with session_factory() as session:
        call = session.get(VoiceCall, identifier)
        binding = session.get(ChannelBinding, call.phone_binding_id)
        if change == "org":
            org = uuid.uuid4()
        elif change == "unverified":
            binding.verified_at = None
        elif change == "owner":
            binding.principal_id = make_principal(session, make_org(session)).id
        elif change == "channel":
            binding.channel = "chat"
        else:
            binding.address = "invalid"
        session.commit()
    provider = Provider()
    result = CallService(session_factory, provider).place(org, identifier)
    assert result == ("not_found" if change == "org" else "not_authorized")
    assert not provider.placements


def test_crash_after_claim_prevents_second_post(session_factory, intent):
    provider = Provider()
    provider.error = KeyboardInterrupt()
    service = CallService(session_factory, provider)
    with pytest.raises(KeyboardInterrupt):
        service.place(*intent)
    assert service.place(*intent) == "reconciliation_required"
    assert len(provider.placements) == 1
    with session_factory() as session:
        assert session.get(VoiceCall, intent[1]).state == "placing"


def test_concurrent_placement_makes_one_post(session_factory, intent):
    started, release = threading.Event(), threading.Event()
    provider = Provider()

    def place(phone, reference):
        provider.placements.append((phone, reference))
        started.set()
        assert release.wait(3)
        return CallReceipt(provider.identifier)

    provider.place_call = place
    service = CallService(session_factory, provider)
    results = []
    worker = threading.Thread(target=lambda: results.append(service.place(*intent)))
    worker.start()
    try:
        assert started.wait(2)
        assert service.place(*intent) == "reconciliation_required"
    finally:
        release.set()
        worker.join(3)
    assert results == ["queued"] and len(provider.placements) == 1


@pytest.mark.parametrize(
    "status",
    ["completed", "no-answer", "busy", "failed", "canceled", "stopped", "error", "balance-low"],
)
def test_terminal_receipt_only_closes_call(session_factory, intent, status):
    provider = Provider()
    service = CallService(session_factory, provider)
    service.place(*intent)
    provider.status = status
    assert service.refresh(*intent) == "closed"
    assert service.place(*intent) == "closed"


def test_reconciliation_mismatch_or_unavailable_never_activates_or_redials(session_factory, intent):
    provider = Provider()
    service = CallService(session_factory, provider)
    service.place(*intent)
    provider.error = VoiceProviderUnavailableError("private")
    assert service.refresh(*intent) == "provider_unavailable"
    provider.error = None
    provider.execution = lambda _: ExecutionStatus(uuid.uuid4(), provider.agent_id, "in-progress")
    assert service.refresh(*intent) == "provider_mismatch"
    assert len(provider.placements) == 1
    assert service.refresh(uuid.uuid4(), intent[1]) == "not_found"
