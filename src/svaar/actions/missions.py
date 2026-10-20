"""Deterministic mission guard for voice calls.

A call's mission fixes its tool allowlist. Neither the LLM nor Jev can expand it;
starting another mission is a separate server-side transition.
"""

from enum import StrEnum


class Mission(StrEnum):
    """Purpose of an outbound call placed by Svaar."""

    ESCALATION = "escalation"
    CLAIM_CHECK = "claim_check"
    PHONE_VERIFY = "phone_verify"
    CONFIRMATION = "confirmation"


MISSION_TOOLS: dict[Mission, frozenset[str]] = {
    Mission.ESCALATION: frozenset(
        {"whoami", "acknowledge_incident", "get_timeline", "list_claims", "confirm_action"}
    ),
    Mission.CLAIM_CHECK: frozenset({"record_claim_answer"}),
    Mission.PHONE_VERIFY: frozenset({"verify_phone_code"}),
    Mission.CONFIRMATION: frozenset({"confirm_action"}),
}


def mission_denial(channel: str, mission: Mission | None, tool: str) -> str | None:
    """Return a denial code when the tool is outside the active mission, else None.

    Voice calls always carry a mission; chat never does.
    """
    if channel == "voice":
        if mission is None:
            return "mission_required"
        if tool not in MISSION_TOOLS[mission]:
            return "outside_mission"
    elif mission is not None:
        return "mission_not_allowed"
    return None
