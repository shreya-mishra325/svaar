"""Identity tool handlers; registered with actions and invoked only by its dispatcher."""

from collections.abc import Mapping
from typing import Any

from svaar.actions.registry import ALL_ROLES, Channel, EmptyArguments, ToolCall, ToolSpec
from svaar.identity.service import verified_channels


def whoami(call: ToolCall) -> Mapping[str, Any]:
    """Describe the resolved caller; never echoes channel addresses."""
    principal = call.principal
    return {
        "principal_id": str(principal.id),
        "org_id": str(principal.org_id),
        "display_name": principal.display_name,
        "role": principal.role,
        "verified_channels": verified_channels(call.session, principal.id),
    }


WHOAMI = ToolSpec(
    name="whoami",
    description="Show who the caller is: name, role, organization and verified channels.",
    arguments=EmptyArguments,
    handler=whoami,
    roles=ALL_ROLES,
    channels=frozenset(Channel),
)
