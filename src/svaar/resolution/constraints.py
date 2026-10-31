"""Hard constraints and change proposals, as typed values that round-trip through JSON.

Each constraint set belongs to one negotiating agent: release schedule, on-call
staffing, or deploy and CI capacity. Times are timezone-aware; naive input is
rejected so a window can never shift with the server's local clock.
"""

from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class Agent(StrEnum):
    """Owner of a constraint set and of the violations it raises."""

    RELEASE = "release"
    STAFFING = "staffing"
    CAPACITY = "capacity"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Window(_Strict):
    """A half-open interval [start, end)."""

    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def _ordered(self) -> "Window":
        if self.end <= self.start:
            raise ValueError("Window end must be after its start")
        return self

    def overlaps(self, start: datetime, end: datetime) -> bool:
        """Whether [start, end) intersects this window."""
        return self.start < end and start < self.end

    def covers(self, start: datetime, end: datetime) -> bool:
        """Whether this window contains all of [start, end)."""
        return self.start <= start and end <= self.end


class FreezeWindow(Window):
    """No changes may land unless every listed approval is present."""

    required_approvals: frozenset[str] = Field(default_factory=frozenset)


class ReleaseSchedule(_Strict):
    """Release agent: freeze windows and the approvals that lift them."""

    freezes: tuple[FreezeWindow, ...] = Field(default=(), max_length=64)


class Shift(Window):
    """One engineer on call for one window."""

    engineer: str = Field(min_length=1, max_length=100)


class OnCallStaffing(_Strict):
    """Staffing agent: who is on call, minimum spare coverage and fatigue limit.

    min_coverage counts on-call engineers other than the one making the change,
    for the whole change window. max_consecutive_hours bounds the assigned
    engineer's continuous on-call time up to the end of the change.
    """

    shifts: tuple[Shift, ...] = Field(default=(), max_length=128)
    min_coverage: int = Field(default=1, ge=0, le=50)
    max_consecutive_hours: float = Field(default=12, gt=0, le=72)


class Deploy(Window):
    """A deploy already holding a slot in one environment."""

    environment: str = Field(min_length=1, max_length=64)


class DeployCapacity(_Strict):
    """Capacity agent: concurrent deploy slots and environment maintenance."""

    max_concurrent_deploys: int = Field(default=1, ge=1, le=50)
    scheduled: tuple[Deploy, ...] = Field(default=(), max_length=128)
    unavailable: dict[str, tuple[Window, ...]] = Field(default_factory=dict)


class Constraints(_Strict):
    """All three agents' hard constraints for one negotiation."""

    release: ReleaseSchedule = ReleaseSchedule()
    staffing: OnCallStaffing = OnCallStaffing()
    capacity: DeployCapacity = DeployCapacity()


class Proposal(_Strict):
    """A concrete change plan the validator can accept or reject."""

    change: str = Field(min_length=1, max_length=200)
    environment: str = Field(min_length=1, max_length=64)
    start: AwareDatetime
    duration_minutes: int = Field(gt=0, le=24 * 60)
    engineer: str = Field(min_length=1, max_length=100)
    approvals: frozenset[str] = Field(default_factory=frozenset)

    @property
    def end(self) -> datetime:
        """End of the change window."""
        return self.start + timedelta(minutes=self.duration_minutes)
