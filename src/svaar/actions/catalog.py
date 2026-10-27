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


def build_registry() -> Registry:
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
    return registry
