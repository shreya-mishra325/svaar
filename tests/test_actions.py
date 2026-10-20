"""The dispatcher is the only path to a handler; tier-2 never runs unconfirmed."""

import threading
import uuid
from collections import Counter
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

import pytest
from factories import make_org, make_principal
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from svaar.actions.catalog import build_registry
from svaar.actions.dispatcher import ApprovalPolicy, Dispatcher, ToolResult
from svaar.actions.missions import MISSION_TOOLS, Mission, mission_denial
from svaar.actions.models import ToolExecution, ToolStatus
from svaar.actions.registry import (
    ALL_ROLES,
    Channel,
    EmptyArguments,
    ProviderOutcomeUnknownError,
    Registry,
    ToolCall,
    ToolContext,
    ToolSpec,
)
from svaar.approvals.models import Confirmation, ConfirmationState
from svaar.identity.models import Org, Principal, Role

calls: Counter[str] = Counter()
lock = threading.Lock()


class RunArguments(BaseModel):
    model_config = {"extra": "forbid"}
    run_id: int


def counting(name: str, error: Exception | None = None):
    def handler(call: ToolCall) -> Mapping[str, Any]:
        with lock:
            calls[name] += 1
        if error is not None:
            call.session.add(Org(name="partial write"))
            call.session.flush()
            raise error
        return {"ran": name}

    return handler


def build_test_registry() -> Registry:
    registry = build_registry()
    chat_only = frozenset({Channel.CHAT})
    leads = frozenset({Role.LEAD, Role.ADMIN})
    for spec in (
        ToolSpec("probe", "Read tool", EmptyArguments, counting("probe"), ALL_ROLES, chat_only),
        ToolSpec("rerun", "Risky", RunArguments, counting("rerun"), leads, chat_only, 2),
        ToolSpec(
            "boom",
            "Fails",
            EmptyArguments,
            counting("boom", RuntimeError("x")),
            ALL_ROLES,
            chat_only,
        ),
        ToolSpec(
            "uncertain",
            "Unknown outcome",
            RunArguments,
            counting("uncertain", ProviderOutcomeUnknownError()),
            leads,
            chat_only,
            2,
        ),
        ToolSpec(
            "conditional",
            "Tier from args",
            RunArguments,
            counting("conditional"),
            ALL_ROLES,
            chat_only,
            lambda call: 2 if call.arguments.run_id > 100 else 1,
        ),
    ):
        registry.register(spec)
    return registry


POLICY = ApprovalPolicy(ttl=timedelta(minutes=10), max_attempts=3, allow_same_channel=False)


@pytest.fixture(autouse=True)
def reset_calls() -> None:
    calls.clear()


@pytest.fixture
def dispatcher() -> Dispatcher:
    return Dispatcher(build_test_registry(), POLICY)


def context(principal: Principal, channel: Channel = Channel.CHAT, mission=None) -> ToolContext:
    return ToolContext(principal.org_id, principal.id, channel, mission, f"turn-{uuid.uuid4()}")


def statuses(session: Session) -> list[tuple[str, str]]:
    rows = session.execute(
        select(ToolExecution.tool, ToolExecution.status).order_by(ToolExecution.created_at)
    )
    return [tuple(row) for row in rows]


# Mission guard: pure, deterministic.


@pytest.mark.parametrize(
    "channel, mission, tool, expected",
    [
        ("voice", None, "whoami", "mission_required"),
        ("voice", Mission.CLAIM_CHECK, "whoami", "outside_mission"),
        ("voice", Mission.PHONE_VERIFY, "confirm_action", "outside_mission"),
        ("voice", Mission.ESCALATION, "whoami", None),
        ("voice", Mission.CONFIRMATION, "confirm_action", None),
        ("chat", Mission.ESCALATION, "whoami", "mission_not_allowed"),
        ("chat", None, "whoami", None),
    ],
)
def test_mission_guard(channel: str, mission: Mission | None, tool: str, expected: str) -> None:
    assert mission_denial(channel, mission, tool) == expected


def test_every_mission_has_an_allowlist() -> None:
    assert set(MISSION_TOOLS) == set(Mission)


def test_duplicate_registration_is_rejected() -> None:
    registry = build_registry()
    with pytest.raises(ValueError):
        registry.register(registry.get("whoami"))


# Dispatcher against PostgreSQL.

pg = pytest.mark.postgres


@pg
def test_unknown_tool_is_recorded(db_session: Session, dispatcher: Dispatcher) -> None:
    principal = make_principal(db_session, make_org(db_session))
    result = dispatcher.dispatch(db_session, context(principal), "drop_tables", {})
    assert result.status is ToolStatus.UNKNOWN_TOOL
    assert statuses(db_session) == [("drop_tables", "unknown_tool")]


@pg
def test_tier_one_runs_and_is_audited(db_session: Session, dispatcher: Dispatcher) -> None:
    principal = make_principal(db_session, make_org(db_session))
    result = dispatcher.dispatch(db_session, context(principal), "whoami", None)
    assert result.status is ToolStatus.SUCCEEDED
    assert result.output["role"] == "dev"
    row = db_session.scalars(select(ToolExecution)).one()
    assert (row.status, row.risk_tier, row.channel) == ("succeeded", 1, "chat")
    assert row.args_hash and row.finished_at is not None


@pg
@pytest.mark.parametrize(
    "tool, channel, mission, reason",
    [
        ("rerun", Channel.CHAT, None, "role_not_allowed"),
        ("probe", Channel.VOICE, Mission.ESCALATION, "channel_not_allowed"),
        ("whoami", Channel.VOICE, None, "mission_required"),
        ("whoami", Channel.VOICE, Mission.CLAIM_CHECK, "outside_mission"),
    ],
)
def test_denials_never_reach_handlers(
    db_session: Session,
    dispatcher: Dispatcher,
    tool: str,
    channel: Channel,
    mission: Mission | None,
    reason: str,
) -> None:
    principal = make_principal(db_session, make_org(db_session), Role.OPS)
    result = dispatcher.dispatch(
        db_session, context(principal, channel, mission), tool, {"run_id": 1}
    )
    assert result.status is ToolStatus.DENIED and result.output["reason"] == reason
    assert not calls


@pg
def test_principal_from_other_org_is_denied(db_session: Session, dispatcher: Dispatcher) -> None:
    principal = make_principal(db_session, make_org(db_session))
    forged = ToolContext(make_org(db_session).id, principal.id, Channel.CHAT, None, "turn")
    assert dispatcher.dispatch(db_session, forged, "probe", {}).output["reason"] == (
        "unknown_principal"
    )


@pg
def test_invalid_arguments_become_tool_errors(db_session: Session, dispatcher: Dispatcher) -> None:
    principal = make_principal(db_session, make_org(db_session), Role.LEAD)
    result = dispatcher.dispatch(
        db_session, context(principal), "rerun", {"run_id": "private-token", "extra": 1}
    )
    assert result.status is ToolStatus.INVALID_ARGUMENTS
    assert "private-token" not in str(result.output)
    assert {tuple(d["location"]) for d in result.output["details"]} == {("run_id",), ("extra",)}
    assert not calls


@pg
def test_handler_failure_rolls_back_its_writes(db_session: Session, dispatcher: Dispatcher) -> None:
    principal = make_principal(db_session, make_org(db_session))
    result = dispatcher.dispatch(db_session, context(principal), "boom", {})
    assert result.status is ToolStatus.FAILED and result.output == {"error": "tool_failed"}
    assert db_session.scalar(select(func.count()).where(Org.name == "partial write")) == 0
    assert statuses(db_session) == [("boom", "failed")]


@pg
def test_available_tools_follow_role_channel_and_mission(
    db_session: Session, dispatcher: Dispatcher
) -> None:
    ops = make_principal(db_session, make_org(db_session), Role.OPS)
    chat = {spec.name for spec in dispatcher.available_tools(db_session, context(ops))}
    assert "rerun" not in chat and {"whoami", "probe", "confirm_action"} <= chat
    voice = dispatcher.available_tools(db_session, context(ops, Channel.VOICE, Mission.CLAIM_CHECK))
    assert voice == []


# Tier-2 confirmation flow.


def request_rerun(session: Session, dispatcher: Dispatcher, principal: Principal) -> ToolResult:
    result = dispatcher.dispatch(session, context(principal), "rerun", {"run_id": 7})
    session.commit()
    return result


def confirm_by_voice(
    session: Session, dispatcher: Dispatcher, principal: Principal, code: str
) -> ToolResult:
    voice = context(principal, Channel.VOICE, Mission.CONFIRMATION)
    result = dispatcher.dispatch(session, voice, "confirm_action", {"code": code})
    session.commit()
    return result


@pytest.fixture
def lead(db_session: Session) -> Principal:
    principal = make_principal(
        db_session,
        make_org(db_session),
        Role.LEAD,
        bindings=(("telegram", "lead-1"), ("phone", "+10000000000")),
    )
    db_session.commit()
    return principal


@pg
def test_tier_two_waits_for_confirmation(
    db_session: Session, dispatcher: Dispatcher, lead: Principal
) -> None:
    result = request_rerun(db_session, dispatcher, lead)
    assert result.status is ToolStatus.CONFIRMATION_REQUIRED
    assert result.ticket is not None and len(result.ticket.nonce) == 6
    assert result.ticket.nonce not in str(result.output)
    assert not calls
    confirmation = db_session.scalars(select(Confirmation)).one()
    assert confirmation.state == "pending" and result.ticket.nonce not in confirmation.nonce_hash


@pg
def test_conditional_tier_uses_validated_arguments(
    db_session: Session, dispatcher: Dispatcher, lead: Principal
) -> None:
    low = dispatcher.dispatch(db_session, context(lead), "conditional", {"run_id": 1})
    high = dispatcher.dispatch(db_session, context(lead), "conditional", {"run_id": 101})
    assert (low.status, high.status) == (ToolStatus.SUCCEEDED, ToolStatus.CONFIRMATION_REQUIRED)
    assert calls["conditional"] == 1


@pg
def test_spoken_code_on_other_channel_runs_once(
    db_session: Session, dispatcher: Dispatcher, lead: Principal
) -> None:
    ticket = request_rerun(db_session, dispatcher, lead).ticket
    spoken = "my code is " + " ".join(ticket.nonce)
    result = confirm_by_voice(db_session, dispatcher, lead, spoken)
    assert result.status is ToolStatus.SUCCEEDED and result.output["result"] == {"ran": "rerun"}
    assert calls["rerun"] == 1

    again = confirm_by_voice(db_session, dispatcher, lead, ticket.nonce)
    assert again.status is ToolStatus.DENIED and calls["rerun"] == 1
    execution = db_session.scalars(
        select(ToolExecution).where(ToolExecution.execution_key.is_not(None))
    ).one()
    assert (execution.status, execution.execution_key) == ("succeeded", str(ticket.confirmation_id))


@pg
def test_same_channel_confirmation_is_refused(
    db_session: Session, dispatcher: Dispatcher, lead: Principal
) -> None:
    ticket = request_rerun(db_session, dispatcher, lead).ticket
    result = dispatcher.dispatch(
        db_session, context(lead), "confirm_action", {"code": ticket.nonce}
    )
    assert result.output["reason"] == "same_channel" and not calls


@pg
def test_wrong_codes_lock_after_limit(
    db_session: Session, dispatcher: Dispatcher, lead: Principal
) -> None:
    ticket = request_rerun(db_session, dispatcher, lead).ticket
    wrong = "000000" if ticket.nonce != "000000" else "111111"
    reasons = [
        confirm_by_voice(db_session, dispatcher, lead, wrong).output["reason"] for _ in "abc"
    ]
    assert reasons == ["no_match", "no_match", "locked"]
    assert confirm_by_voice(db_session, dispatcher, lead, ticket.nonce).output["reason"] == (
        "no_match"
    )
    assert not calls


@pg
def test_model_yes_is_not_a_confirmation(
    db_session: Session, dispatcher: Dispatcher, lead: Principal
) -> None:
    request_rerun(db_session, dispatcher, lead)
    assert confirm_by_voice(db_session, dispatcher, lead, "yes, confirmed").status is (
        ToolStatus.DENIED
    )
    assert not calls


@pg
def test_expired_confirmation_cannot_run(
    db_session: Session, dispatcher: Dispatcher, lead: Principal
) -> None:
    ticket = request_rerun(db_session, dispatcher, lead).ticket
    db_session.execute(update(Confirmation).values(expires_at=func.now() - timedelta(seconds=1)))
    db_session.commit()
    assert confirm_by_voice(db_session, dispatcher, lead, ticket.nonce).status is ToolStatus.DENIED
    assert not calls


@pg
def test_other_principal_cannot_confirm(
    db_session: Session, dispatcher: Dispatcher, lead: Principal
) -> None:
    ticket = request_rerun(db_session, dispatcher, lead).ticket
    other = make_principal(db_session, make_org(db_session, "Other"), Role.ADMIN)
    db_session.commit()
    assert confirm_by_voice(db_session, dispatcher, other, ticket.nonce).status is (
        ToolStatus.DENIED
    )
    assert not calls


@pg
def test_authorization_is_rechecked_at_execution(
    db_session: Session, dispatcher: Dispatcher, lead: Principal
) -> None:
    ticket = request_rerun(db_session, dispatcher, lead).ticket
    db_session.execute(update(Principal).values(role=Role.OPS.value))
    db_session.commit()
    result = confirm_by_voice(db_session, dispatcher, lead, ticket.nonce)
    assert result.output == {"confirmed": True, "reason": "role_not_allowed"}
    assert not calls
    assert ("rerun", "denied") in statuses(db_session)


@pg
def test_uncertain_provider_outcome_is_recorded(
    db_session: Session, dispatcher: Dispatcher, lead: Principal
) -> None:
    result = dispatcher.dispatch(db_session, context(lead), "uncertain", {"run_id": 1})
    db_session.commit()
    confirmed = confirm_by_voice(db_session, dispatcher, lead, result.ticket.nonce)
    assert confirmed.status is ToolStatus.OUTCOME_UNKNOWN
    assert ("uncertain", "outcome_unknown") in statuses(db_session)
    assert calls["uncertain"] == 1


@pg
def test_concurrent_confirmations_execute_once(
    session_factory: sessionmaker[Session], dispatcher: Dispatcher, lead: Principal
) -> None:
    with session_factory() as session:
        ticket = request_rerun(session, dispatcher, lead).ticket
    barrier = threading.Barrier(4)
    results: list[ToolStatus] = []

    def attempt() -> None:
        with session_factory() as session:
            barrier.wait()
            results.append(confirm_by_voice(session, dispatcher, lead, ticket.nonce).status)

    threads = [threading.Thread(target=attempt) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results).count(ToolStatus.SUCCEEDED) == 1
    assert calls["rerun"] == 1
    with session_factory() as session:
        state = session.scalar(select(Confirmation.state))
        assert state == ConfirmationState.CONFIRMED.value
