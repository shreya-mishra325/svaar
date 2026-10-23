"""The narrow verification tool; only actions dispatch may invoke this handler."""

from pydantic import BaseModel, Field

from svaar.actions.missions import Mission
from svaar.actions.registry import ALL_ROLES, Channel, ToolCall, ToolSpec
from svaar.identity.phones import verify_phone_challenge


class PhoneCodeArguments(BaseModel):
    """The exact caller transcript, never a model's reconstructed code."""

    model_config = {"extra": "forbid"}
    code: str = Field(min_length=1, max_length=20000, repr=False)


def verify_phone_code(call: ToolCall) -> dict[str, object]:
    """Resolve the challenge exclusively from trusted call context."""
    if call.context.mission is not Mission.PHONE_VERIFY:
        return {"verified": False, "reason": "outside_mission"}
    assert isinstance(call.arguments, PhoneCodeArguments)
    return verify_phone_challenge(
        call.session,
        org_id=call.context.org_id,
        principal_id=call.context.principal_id,
        challenge_id=call.context.phone_challenge_id,
        spoken=call.arguments.code,
    )


VERIFY_PHONE_CODE = ToolSpec(
    name="verify_phone_code",
    description="Verify this call's pending phone challenge using the caller's exact spoken code.",
    arguments=PhoneCodeArguments,
    handler=verify_phone_code,
    roles=ALL_ROLES,
    channels=frozenset({Channel.VOICE}),
)
