"""Deterministic validation of a change proposal against every hard constraint.

The validator is the final word: models and negotiating agents may suggest
proposals, but only a proposal with no violations is ever accepted. It reports
every violation, in a stable order, so a revision can address all of them.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from svaar.resolution.constraints import Agent, Constraints, OnCallStaffing, Proposal


@dataclass(frozen=True, order=True)
class Violation:
    """One broken hard constraint, attributed to the agent that owns it."""

    agent: Agent
    code: str
    detail: str


@dataclass(frozen=True)
class ValidationResult:
    """Validator verdict; valid exactly when there are no violations."""

    violations: tuple[Violation, ...]

    @property
    def valid(self) -> bool:
        """Whether the proposal satisfies every hard constraint."""
        return not self.violations


def validate(proposal: Proposal, constraints: Constraints) -> ValidationResult:
    """Check a proposal against release, staffing and capacity constraints."""
    violations = [
        *_release(proposal, constraints),
        *_staffing(proposal, constraints.staffing),
        *_capacity(proposal, constraints),
    ]
    return ValidationResult(tuple(sorted(violations)))


def _release(proposal: Proposal, constraints: Constraints) -> list[Violation]:
    found = []
    for freeze in constraints.release.freezes:
        if not freeze.overlaps(proposal.start, proposal.end):
            continue
        missing = sorted(freeze.required_approvals - proposal.approvals)
        if missing or not freeze.required_approvals:
            needed = ", ".join(missing) if missing else "none can lift it"
            found.append(
                Violation(
                    Agent.RELEASE,
                    "freeze_window",
                    f"Overlaps the freeze {_span(freeze.start, freeze.end)}; "
                    f"missing approvals: {needed}",
                )
            )
    return found


def _staffing(proposal: Proposal, staffing: OnCallStaffing) -> list[Violation]:
    found = []
    start, end = proposal.start, proposal.end
    own = [s for s in staffing.shifts if s.engineer == proposal.engineer]
    if not _covered(own, start, end):
        found.append(
            Violation(
                Agent.STAFFING,
                "engineer_off_shift",
                f"{proposal.engineer} is not on call for all of {_span(start, end)}",
            )
        )
    else:
        hours = _continuous_hours(own, start, end)
        if hours > staffing.max_consecutive_hours:
            found.append(
                Violation(
                    Agent.STAFFING,
                    "consecutive_hours",
                    f"{proposal.engineer} would be on call {hours:g} hours in a row; "
                    f"limit {staffing.max_consecutive_hours:g}",
                )
            )
    others = {
        shift.engineer
        for shift in staffing.shifts
        if shift.engineer != proposal.engineer
        and _covered([s for s in staffing.shifts if s.engineer == shift.engineer], start, end)
    }
    if len(others) < staffing.min_coverage:
        found.append(
            Violation(
                Agent.STAFFING,
                "coverage",
                f"Only {len(others)} other engineer(s) on call during the change; "
                f"need {staffing.min_coverage}",
            )
        )
    return found


def _capacity(proposal: Proposal, constraints: Constraints) -> list[Violation]:
    capacity = constraints.capacity
    found = []
    start, end = proposal.start, proposal.end
    busy = [d for d in capacity.scheduled if d.overlaps(start, end)]
    if len(busy) >= capacity.max_concurrent_deploys:
        found.append(
            Violation(
                Agent.CAPACITY,
                "deploy_capacity",
                f"{len(busy)} deploy(s) already hold the "
                f"{capacity.max_concurrent_deploys} slot(s) during {_span(start, end)}",
            )
        )
    for window in capacity.unavailable.get(proposal.environment, ()):
        if window.overlaps(start, end):
            found.append(
                Violation(
                    Agent.CAPACITY,
                    "environment_unavailable",
                    f"{proposal.environment} is unavailable {_span(window.start, window.end)}",
                )
            )
    return found


def _covered(shifts, start: datetime, end: datetime) -> bool:
    """Whether the union of shifts covers [start, end) without a gap."""
    cursor = start
    for shift in sorted(shifts, key=lambda s: s.start):
        if shift.start > cursor:
            break
        cursor = max(cursor, shift.end)
        if cursor >= end:
            return True
    return cursor >= end


def _continuous_hours(shifts, start: datetime, end: datetime) -> float:
    """Length of the unbroken on-call run that contains [start, end), up to end."""
    ordered = sorted(shifts, key=lambda s: s.start)
    run_start = start
    changed = True
    while changed:
        changed = False
        for shift in ordered:
            if shift.start < run_start <= shift.end:
                run_start = shift.start
                changed = True
    return round((end - run_start) / timedelta(hours=1), 2)


def _span(start: datetime, end: datetime) -> str:
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    if start.date() == end.date():
        return f"{start:%Y-%m-%d %H:%M}-{end:%H:%M} UTC"
    return f"{start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M} UTC"
