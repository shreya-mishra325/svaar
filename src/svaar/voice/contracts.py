"""Synchronous composition contract for the shared conversational agent."""

from typing import Protocol


class TurnRunner(Protocol):
    """Run one conversational turn for a resolved call and return text to speak.

    Application composition injects an implementation from agent. Neither agent
    nor voice imports the other package's implementation.
    """

    def run_turn(self, call_id: str, text: str) -> str:
        """Process caller text within the call's existing identity and mission.

        Args:
            call_id: Identifier of the Svaar voice call.
            text: The caller's transcribed words for this turn.

        Returns:
            Short spoken-style reply text.
        """
        ...
