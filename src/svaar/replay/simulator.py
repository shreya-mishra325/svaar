"""A fake, in-memory CI runner for replaying a corrected pipeline.

It performs no I/O: no network, no database, no clock. Step outcomes come only
from the scenario, so the same scenario always produces the same simulation.
A simulated success is never evidence that production recovered.
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SIMULATED = "simulated"
LABEL = "SIMULATION: no real pipeline ran; this is not evidence of production recovery."


class Step(BaseModel):
    """One pipeline step and its outcome in the recorded failing run."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(min_length=1, max_length=100)
    recorded: Literal["success", "failure"]
    seconds: int = Field(default=60, ge=0, le=86400)


class Scenario(BaseModel):
    """A recorded pipeline and the steps a proposed correction claims to fix."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    steps: tuple[Step, ...] = Field(min_length=1, max_length=50)
    fixes: frozenset[str] = Field(default_factory=frozenset)
    correction: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def _known_steps(self) -> "Scenario":
        names = [step.name for step in self.steps]
        if len(set(names)) != len(names):
            raise ValueError("Step names must be unique")
        if not self.fixes <= set(names):
            raise ValueError("Fixes must name existing steps")
        return self


@dataclass(frozen=True)
class SimulatedStep:
    """A step's outcome in the simulation."""

    name: str
    outcome: Literal["success", "failure", "not_run"]
    offset_seconds: int


@dataclass(frozen=True)
class Simulation:
    """The whole simulated run; kind is always simulated."""

    conclusion: Literal["success", "failure"]
    steps: tuple[SimulatedStep, ...]
    kind: str = SIMULATED
    label: str = LABEL


def simulate(scenario: Scenario) -> Simulation:
    """Run steps in order; a step fails if it failed when recorded and is not fixed.

    The first failure stops the pipeline and later steps are reported not_run.
    """
    results = []
    offset = 0
    failed = False
    for step in scenario.steps:
        if failed:
            results.append(SimulatedStep(step.name, "not_run", offset))
            continue
        outcome = (
            "success" if step.recorded == "success" or step.name in scenario.fixes else "failure"
        )
        results.append(SimulatedStep(step.name, outcome, offset))
        offset += step.seconds
        failed = outcome == "failure"
    return Simulation(conclusion="failure" if failed else "success", steps=tuple(results))
