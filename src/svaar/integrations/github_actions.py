"""Explicitly write-enabled GitHub Actions client; never used by log enrichment.

Contracts verified 2026-10-28:
https://docs.github.com/en/rest/actions/workflow-runs#re-run-a-workflow
https://docs.github.com/en/rest/actions/workflow-runs#cancel-a-workflow-run
"""

import re
from dataclasses import dataclass
from time import monotonic

import httpx

from svaar.integrations.github_app import GithubAppClient, GithubUnavailableError, _Attempt


class GithubActionRejectedError(Exception):
    """The provider explicitly refused a mutation, with no response body exposed."""


class GithubActionUnknownError(Exception):
    """The mutation may have reached GitHub; never automatically retry."""


@dataclass(frozen=True)
class ActionReceipt:
    """Acknowledgement only, never proof that a workflow ran or recovered."""

    status_code: int
    request_id: str | None


class GithubActionsClient(GithubAppClient):
    """Dedicated writer requests Actions write permission only after confirmation."""

    def token_permissions(self) -> dict[str, str]:
        """Read clients keep read-only tokens; this separate adapter needs write."""
        return {"actions": "write", "metadata": "read"}

    def _request(self, method: str, path: str, token: str, *, body: dict | None = None) -> dict:
        deadline = getattr(self, "_action_deadline", None)
        remaining = 6.0 if deadline is None else min(6.0, deadline - monotonic())
        if remaining <= 0:
            raise GithubUnavailableError("Action deadline exceeded before request")
        self._http.timeout = httpx.Timeout(remaining, connect=min(2, remaining))
        return super()._request(method, path, token, body=body)

    def execute(
        self,
        action: str,
        run_id: int,
        run_attempt: int,
        head_sha: str,
        *,
        deadline: float | None = None,
    ) -> ActionReceipt:
        """Verify the current target before one POST; never retry or follow redirects."""
        if action not in {"rerun_workflow", "cancel_run"}:
            raise ValueError("Unsupported GitHub action")
        if deadline is not None and deadline - monotonic() < 1:
            raise GithubUnavailableError("Action deadline exceeded before provider request")
        self._action_deadline = deadline
        name = self.repository_name()
        current = _Attempt.model_validate(
            self._request("GET", f"repos/{name}/actions/runs/{run_id}", self._access_token())
        )
        if (
            current.id != run_id
            or current.repository.id != self._repository_id
            or current.run_attempt != run_attempt
            or current.head_sha != head_sha
        ):
            raise GithubActionRejectedError("Workflow target changed")
        if (
            action == "rerun_workflow"
            and current.status != "completed"
            or action == "cancel_run"
            and current.status not in {"queued", "in_progress", "waiting", "pending", "requested"}
        ):
            raise GithubActionRejectedError("Workflow state changed")
        remaining = 6.0 if deadline is None else min(6.0, deadline - monotonic())
        if remaining <= 0:
            raise GithubUnavailableError("Action deadline exceeded before mutation")
        token = self._access_token()
        suffix, expected = ("rerun", 201) if action == "rerun_workflow" else ("cancel", 202)
        try:
            with self._http.stream(
                "POST",
                f"repos/{name}/actions/runs/{run_id}/{suffix}",
                headers={"Authorization": "Bearer " + token},
                timeout=httpx.Timeout(remaining, connect=min(2, remaining)),
            ) as response:
                if response.status_code in {400, 401, 403, 404, 409, 410, 422, 429}:
                    raise GithubActionRejectedError("GitHub action rejected")
                if response.status_code != expected:
                    raise GithubActionUnknownError("GitHub action outcome unknown")
                request_id = response.headers.get("X-GitHub-Request-Id")
                if (
                    request_id is not None
                    and re.fullmatch(r"[A-Za-z0-9:-]{1,128}", request_id) is None
                ):
                    request_id = None
                return ActionReceipt(response.status_code, request_id)
        except httpx.HTTPError:
            raise GithubActionUnknownError("GitHub action outcome unknown") from None
