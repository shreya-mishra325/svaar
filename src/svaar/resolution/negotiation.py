"""Bounded, deterministic negotiation between the release, capacity and staffing agents.

Each round the validator judges the current proposal. If it is rejected, each
agent revises only what it owns: release and capacity move the start time, and
staffing reassigns the engineer. Agents never add approvals or relax constraints.
The same input always yields the same rounds; an unresolved conflict is rejected.
"""

from dataclasses import dataclass
from datetime import datetime

from svaar.resolution.constraints import Agent, Constraints, Proposal
from svaar.resolution.validator import ValidationResult, validate

MAX_ROUNDS = 5


@dataclass(frozen=True)
class Round:
    """One proposal and the validator's verdict on it."""

    index: int
    proposal: Proposal
    result: ValidationResult
    revised_by: tuple[Agent, ...]


@dataclass(frozen=True)
class Outcome:
    """Every round in order, and the accepted proposal if one passed validation."""

    rounds: tuple[Round, ...]
    accepted: Proposal | None


def negotiate(
    proposal: Proposal, constraints: Constraints, max_rounds: int = MAX_ROUNDS
) -> Outcome:
    """Revise a proposal until the validator accepts it or the round limit is reached."""
    rounds = []
    revised_by: tuple[Agent, ...] = ()
    seen = set()
    for index in range(max_rounds):
        result = validate(proposal, constraints)
        rounds.append(Round(index, proposal, result, revised_by))
        if result.valid:
            return Outcome(tuple(rounds), proposal)
        seen.add(proposal)
        revised, revised_by = _revise(proposal, constraints, result)
        if revised in seen:
            break  # no agent can make progress; stop rather than loop
        proposal = revised
    return Outcome(tuple(rounds), None)


def _revise(
    proposal: Proposal, constraints: Constraints, result: ValidationResult
) -> tuple[Proposal, tuple[Agent, ...]]:
    codes = {v.code for v in result.violations}
    changed = []
    start = proposal.start
    end = proposal.end

    if "freeze_window" in codes:
        blocking = [
            freeze.end
            for freeze in constraints.release.freezes
            if freeze.overlaps(start, end)
            and (
                not freeze.required_approvals or not freeze.required_approvals <= proposal.approvals
            )
        ]
        if blocking:
            start = max(start, max(blocking))
            changed.append(Agent.RELEASE)

    if codes & {"deploy_capacity", "environment_unavailable"} or start != proposal.start:
        moved = _next_capacity_slot(proposal.model_copy(update={"start": start}), constraints)
        if moved != start:
            start = moved
            changed.append(Agent.CAPACITY)

    candidate = proposal.model_copy(update={"start": start})
    staffing_codes = {"engineer_off_shift", "consecutive_hours"}
    if staffing_codes & {v.code for v in validate(candidate, constraints).violations}:
        engineer = _replacement(candidate, constraints)
        if engineer is not None:
            candidate = candidate.model_copy(update={"engineer": engineer})
            changed.append(Agent.STAFFING)
    return candidate, tuple(changed)


def _next_capacity_slot(proposal: Proposal, constraints: Constraints) -> datetime:
    """Earliest start, not before the proposal's, free of busy slots and maintenance."""
    capacity = constraints.capacity
    duration = proposal.end - proposal.start
    start = proposal.start
    for _ in range(64):
        end = start + duration
        busy = [d for d in capacity.scheduled if d.overlaps(start, end)]
        blocked = [
            w for w in capacity.unavailable.get(proposal.environment, ()) if w.overlaps(start, end)
        ]
        if len(busy) < capacity.max_concurrent_deploys and not blocked:
            return start
        candidates = [w.end for w in blocked]
        if len(busy) >= capacity.max_concurrent_deploys:
            candidates.append(min(d.end for d in busy))
        start = max(start, min(candidates))
    return start


def _replacement(proposal: Proposal, constraints: Constraints) -> str | None:
    """First engineer, alphabetically, for whom the staffing agent raises nothing."""
    engineers = sorted({s.engineer for s in constraints.staffing.shifts} - {proposal.engineer})
    for engineer in engineers:
        trial = proposal.model_copy(update={"engineer": engineer})
        if not any(v.agent is Agent.STAFFING for v in validate(trial, constraints).violations):
            return engineer
    return None
