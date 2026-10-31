"""Table-driven validator tests: every hard constraint, including must-reject cases."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from svaar.resolution.constraints import (
    Agent,
    Constraints,
    Deploy,
    DeployCapacity,
    FreezeWindow,
    OnCallStaffing,
    Proposal,
    ReleaseSchedule,
    Shift,
    Window,
)
from svaar.resolution.validator import validate

DAY = datetime(2026, 10, 28, tzinfo=UTC)


def at(hour: float) -> datetime:
    return DAY + timedelta(hours=hour)


def shift(engineer, start, end):
    return Shift(engineer=engineer, start=at(start), end=at(end))


BASE = Constraints(
    release=ReleaseSchedule(
        freezes=(FreezeWindow(start=at(0), end=at(12), required_approvals={"lead", "release"}),)
    ),
    staffing=OnCallStaffing(
        shifts=(shift("asha", 8, 20), shift("ravi", 0, 16), shift("meera", 14, 23)),
        min_coverage=1,
        max_consecutive_hours=12,
    ),
    capacity=DeployCapacity(
        max_concurrent_deploys=1,
        scheduled=(Deploy(environment="prod", start=at(13), end=at(14)),),
        unavailable={"prod": (Window(start=at(18), end=at(19)),)},
    ),
)


def proposal(**overrides):
    values = {
        "change": "hotfix-42",
        "environment": "prod",
        "start": at(15),
        "duration_minutes": 30,
        "engineer": "asha",
        "approvals": frozenset(),
    }
    values.update(overrides)
    return Proposal(**values)


def codes(result):
    return [(v.agent, v.code) for v in result.violations]


def test_valid_revision_is_accepted():
    result = validate(proposal(), BASE)
    assert result.valid and result.violations == ()


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"start": at(10)}, [(Agent.RELEASE, "freeze_window")]),
        ({"start": at(13.5)}, [(Agent.CAPACITY, "deploy_capacity")]),
        ({"start": at(18.5)}, [(Agent.CAPACITY, "environment_unavailable")]),
        ({"engineer": "meera", "start": at(12.5)}, [(Agent.STAFFING, "engineer_off_shift")]),
        ({"engineer": "nobody"}, [(Agent.STAFFING, "engineer_off_shift")]),
    ],
)
def test_single_violations(overrides, expected):
    assert codes(validate(proposal(**overrides), BASE)) == expected


def test_freeze_lifted_only_by_all_required_approvals():
    partial = validate(proposal(start=at(11), approvals={"lead"}), BASE)
    assert codes(partial) == [(Agent.RELEASE, "freeze_window")]
    assert "release" in partial.violations[0].detail
    assert validate(proposal(start=at(11), approvals={"lead", "release"}), BASE).valid


def test_hard_freeze_without_approvals_cannot_be_lifted():
    hard = BASE.model_copy(
        update={"release": ReleaseSchedule(freezes=(FreezeWindow(start=at(14), end=at(16)),))}
    )
    result = validate(proposal(approvals={"lead", "release", "admin"}), hard)
    assert codes(result) == [(Agent.RELEASE, "freeze_window")]


def test_coverage_excludes_the_engineer_doing_the_change():
    thin = BASE.model_copy(
        update={"staffing": OnCallStaffing(shifts=(shift("asha", 8, 20),), min_coverage=1)}
    )
    assert codes(validate(proposal(), thin)) == [(Agent.STAFFING, "coverage")]


def test_consecutive_hours_counts_back_to_run_start_across_adjacent_shifts():
    tired = BASE.model_copy(
        update={
            "staffing": OnCallStaffing(
                shifts=(shift("asha", 2, 10), shift("asha", 10, 20), shift("ravi", 0, 23)),
                max_consecutive_hours=12,
            )
        }
    )
    result = validate(proposal(start=at(15)), tired)
    assert codes(result) == [(Agent.STAFFING, "consecutive_hours")]
    assert "13.5 hours" in result.violations[0].detail


def test_demo_conflict_reports_every_violation_in_stable_order():
    """The demo hotfix: inside the freeze, off-shift engineer, competing deploy slot."""
    conflict = proposal(start=at(11.5), duration_minutes=120, engineer="meera")
    assert codes(validate(conflict, BASE)) == [
        (Agent.CAPACITY, "deploy_capacity"),
        (Agent.RELEASE, "freeze_window"),
        (Agent.STAFFING, "engineer_off_shift"),
    ]


def test_capacity_counts_concurrent_slots():
    roomy = BASE.model_copy(
        update={
            "capacity": DeployCapacity(
                max_concurrent_deploys=2,
                scheduled=(Deploy(environment="stage", start=at(13), end=at(14)),),
            )
        }
    )
    assert validate(proposal(start=at(13.5)), roomy).valid


def test_naive_and_reversed_times_are_rejected():
    with pytest.raises(ValidationError):
        proposal(start=datetime(2026, 10, 28, 15))
    with pytest.raises(ValidationError):
        Window(start=at(5), end=at(5))


def test_constraints_round_trip_through_json():
    assert Constraints.model_validate_json(BASE.model_dump_json()) == BASE


# Negotiation: bounded, deterministic revision rounds judged by the validator.


def test_demo_conflict_is_rejected_then_a_revision_is_accepted():
    from svaar.resolution.negotiation import negotiate

    conflict = proposal(start=at(11.5), duration_minutes=120, engineer="meera")
    outcome = negotiate(conflict, BASE)
    assert not outcome.rounds[0].result.valid
    assert outcome.accepted is not None and validate(outcome.accepted, BASE).valid
    # Release moves past the freeze, capacity past the 13:00 deploy; meera is then on shift.
    assert outcome.accepted.start == at(14) and outcome.accepted.engineer == "meera"
    assert outcome.rounds[1].revised_by == (Agent.RELEASE, Agent.CAPACITY)
    assert outcome.accepted.approvals == conflict.approvals  # agents never add approvals


def test_staffing_agent_reassigns_when_time_cannot_help():
    from svaar.resolution.negotiation import negotiate

    outcome = negotiate(proposal(engineer="nobody"), BASE)
    assert outcome.accepted is not None and outcome.accepted.engineer == "asha"
    assert outcome.rounds[-1].revised_by == (Agent.STAFFING,)


def test_unresolvable_conflict_is_rejected_within_the_round_limit():
    from svaar.resolution.negotiation import MAX_ROUNDS, negotiate

    nobody = BASE.model_copy(update={"staffing": OnCallStaffing(shifts=(), min_coverage=1)})
    outcome = negotiate(proposal(), nobody)
    assert outcome.accepted is None and 1 <= len(outcome.rounds) <= MAX_ROUNDS
    assert all(not r.result.valid for r in outcome.rounds)


def test_negotiation_is_deterministic():
    from svaar.resolution.negotiation import negotiate

    conflict = proposal(start=at(11.5), duration_minutes=120, engineer="meera")
    assert negotiate(conflict, BASE) == negotiate(conflict, BASE)


def test_approval_sets_serialize_in_sorted_order():
    # Set iteration follows per-process string hashing; stored snapshots and
    # confirmation hashes must not.
    names = {f"approver-{n:02d}" for n in range(40)}
    freeze = FreezeWindow(start=at(0), end=at(1), required_approvals=names)
    plan = proposal(start=at(2), duration_minutes=30, engineer="asha").model_copy(
        update={"approvals": frozenset(names)}
    )
    assert freeze.model_dump(mode="json")["required_approvals"] == sorted(names)
    assert plan.model_dump(mode="json")["approvals"] == sorted(names)
    restored = Constraints.model_validate(BASE.model_dump(mode="json"))
    assert restored.model_dump(mode="json") == BASE.model_dump(mode="json")
