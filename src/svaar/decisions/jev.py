"""Vercel's TypeSafe-compatible Jev adapter, currently exercised with HTTP mocks.

Contract references:
https://vercel.com/docs/ai-gateway/sdks-and-apis/typesafe
https://docs.typesafe.ai/primitives/choice

This adapter is deliberately not composed into application startup yet. It reads
no environment files and never substitutes a chat model for a decision model.
"""

import math
from collections.abc import Sequence

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictFloat, StrictInt

from svaar.decisions.policy import is_valid
from svaar.decisions.questions import Question
from svaar.decisions.types import Decision, DecisionUnavailableError

_MODELS = {"typesafe-ai/jev-1.13.0", "typesafe-ai/jev-1.14.0"}


class _ChoiceAnswer(BaseModel):
    """Require real provider statistics, without coercing strings or booleans."""

    model_config = ConfigDict(strict=True)

    type: str
    choice: str
    confidence: StrictFloat | StrictInt = Field(ge=0, le=1, allow_inf_nan=False)
    probabilities: dict[str, StrictFloat | StrictInt]


class VercelJevEngine:
    """Translate the existing DecisionEngine protocol into Gateway System One HTTP.

    Credentials are explicitly supplied and sent only to Vercel. HTTP retries and
    model fallbacks are disabled. The agent's inference deadline bounds total wait;
    HTTP timeouts bound individual network operations, not total turn latency.
    """

    def __init__(
        self,
        *,
        api_key: SecretStr,
        model: str,
        timeout: float = 2.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if model not in _MODELS:
            raise ValueError("Select an explicitly supported, versioned Vercel Jev model")
        if not api_key.get_secret_value().strip():
            raise ValueError("A Vercel AI Gateway key is required")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Jev timeout must be finite and positive")
        self.model = model
        self._client = httpx.Client(
            base_url="https://ai-gateway.vercel.sh/typesafe/",
            headers={"Authorization": f"Bearer {api_key.get_secret_value()}"},
            timeout=httpx.Timeout(timeout, connect=min(timeout, 1.0)),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def close(self) -> None:
        """Release HTTP connections; the composition owner must call this."""
        self._client.close()

    def decide(self, state: str, questions: Sequence[Question]) -> list[Decision]:
        """Return independently valid answers; DecisionService supplies fallbacks.

        Call through DecisionService so redaction, policy and audit stay in place.
        The returned model must match the requested pinned version. A malformed
        answer is omitted without discarding valid siblings in a batch.
        """
        if not questions:
            return []
        if len({q.name for q in questions}) != len(questions):
            raise ValueError("Decision question names must be unique")
        try:
            response = self._client.post(
                "v1/systemone",
                json={
                    "model": self.model,
                    "state": state,
                    "questions": {
                        q.name: {
                            "type": q.kind,
                            "instructions": (
                                f"Choose the {q.name.replace('_', ' ')} label "
                                "that best matches the state using these criteria."
                            ),
                            "criteria": q.criteria,
                        }
                        for q in questions
                    },
                },
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError):
            raise DecisionUnavailableError("Jev request failed") from None
        if (
            not isinstance(body, dict)
            or body.get("model") != self.model
            or not isinstance(body.get("answers"), dict)
        ):
            raise DecisionUnavailableError("Invalid Jev response envelope")
        decisions = []
        for question in questions:
            try:
                answer = _ChoiceAnswer.model_validate(body["answers"].get(question.name))
            except ValueError:
                continue
            decision = Decision(
                question.name,
                answer.choice,
                answer.confidence,
                probabilities=answer.probabilities,
                model_version=body["model"],
            )
            if (
                answer.type == "choice"
                and is_valid(decision, question)
                and set(answer.probabilities) == set(question.labels)
                and math.isclose(sum(answer.probabilities.values()), 1.0, abs_tol=0.001)
                and answer.probabilities[answer.choice] == max(answer.probabilities.values())
            ):
                decisions.append(decision)
        return decisions
