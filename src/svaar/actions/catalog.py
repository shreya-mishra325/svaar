"""Registry composition: every implemented tool is registered here, and only here."""

from svaar.actions.registry import Registry
from svaar.identity.phone_tools import VERIFY_PHONE_CODE
from svaar.identity.tools import WHOAMI
from svaar.incidents.tools import (
    ACKNOWLEDGE_INCIDENT,
    CHECK_CLAIM,
    GET_TIMELINE,
    LIST_CLAIMS,
    LIST_INCIDENTS,
    RECORD_CLAIM,
)
from svaar.integrations.ci_action_tools import ExecuteAction, ci_action_tools
from svaar.integrations.ci_tools import EXPLAIN_CI_FAILURE, LIST_CI_RUNS
from svaar.replay.tools import REQUEST_REPLAY
from svaar.resolution.tools import APPROVE_EXCEPTION, START_NEGOTIATION


def build_registry(*, ci_actions: ExecuteAction | None = None) -> Registry:
    """Return a registry of all implemented business tools."""
    registry = Registry()
    registry.register(WHOAMI)
    registry.register(VERIFY_PHONE_CODE)
    registry.register(GET_TIMELINE)
    registry.register(LIST_INCIDENTS)
    registry.register(ACKNOWLEDGE_INCIDENT)
    registry.register(RECORD_CLAIM)
    registry.register(CHECK_CLAIM)
    registry.register(LIST_CLAIMS)
    registry.register(START_NEGOTIATION)
    registry.register(APPROVE_EXCEPTION)
    registry.register(REQUEST_REPLAY)
    registry.register(LIST_CI_RUNS)
    registry.register(EXPLAIN_CI_FAILURE)
    if ci_actions is not None:
        for spec in ci_action_tools(ci_actions):
            registry.register(spec)
    return registry
