"""Mutation adapter contracts with synthetic signing keys and mocked HTTP."""

import json
from datetime import timedelta
from time import monotonic

import httpx
import pytest
from pydantic import SecretStr
from test_github_app import NOW
from test_github_app import key as key

from svaar.integrations.github_actions import (
    GithubActionRejectedError,
    GithubActionsClient,
    GithubActionUnknownError,
)
from svaar.integrations.github_app import GithubUnavailableError


def client(key, requests, *, status=201, attempt=1, timeout=False):
    def handle(request):
        requests.append(request)
        path = request.url.path
        assert request.url.host == "api.github.com"
        if path == "/app/installations/8/access_tokens":
            assert json.loads(request.content)["permissions"]["actions"] == "write"
            return httpx.Response(
                201,
                json={
                    "token": "fake-write-token",
                    "expires_at": (NOW + timedelta(hours=1)).isoformat(),
                },
            )
        if path == "/repositories/9":
            return httpx.Response(200, json={"id": 9, "full_name": "team/repo"})
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 10,
                    "repository": {"id": 9, "full_name": "team/repo"},
                    "run_attempt": attempt,
                    "workflow_id": 55,
                    "head_sha": "a" * 40,
                    "head_branch": "main",
                    "status": "completed" if status != 202 else "in_progress",
                    "conclusion": "failure" if status != 202 else None,
                },
            )
        assert path in {
            "/repos/team/repo/actions/runs/10/rerun",
            "/repos/team/repo/actions/runs/10/cancel",
        }
        if timeout:
            raise httpx.ReadTimeout("simulated private error")
        return httpx.Response(status, headers={"X-GitHub-Request-Id": "ABC:123"})

    return GithubActionsClient(
        app_id=7,
        private_key_b64=SecretStr(key[1]),
        installation_id=8,
        repository_id=9,
        transport=httpx.MockTransport(handle),
        now=lambda: NOW,
    )


@pytest.mark.parametrize("action,status", [("rerun_workflow", 201), ("cancel_run", 202)])
def test_exact_mutation_receipt_is_acceptance_only(key, action, status):
    requests = []
    provider = client(key, requests, status=status)
    try:
        receipt = provider.execute(action, 10, 1, "a" * 40)
        assert receipt.status_code == status and receipt.request_id == "ABC:123"
        assert (
            sum(
                request.method == "POST" and "/access_tokens" not in request.url.path
                for request in requests
            )
            == 1
        )
    finally:
        provider.close()


@pytest.mark.parametrize(
    "status,error",
    [
        (403, GithubActionRejectedError),
        (409, GithubActionRejectedError),
        (500, GithubActionUnknownError),
        (302, GithubActionUnknownError),
    ],
)
def test_mutation_errors_never_retry_or_follow_redirects(key, status, error):
    requests = []
    provider = client(key, requests, status=status)
    try:
        with pytest.raises(error):
            provider.execute("rerun_workflow", 10, 1, "a" * 40)
        assert sum(request.url.path.endswith("/rerun") for request in requests) == 1
    finally:
        provider.close()


def test_timeout_is_unknown_and_attempt_changes_prevent_post(key):
    requests = []
    provider = client(key, requests, timeout=True)
    with pytest.raises(GithubActionUnknownError):
        provider.execute("rerun_workflow", 10, 1, "a" * 40)
    provider.close()
    requests = []
    provider = client(key, requests, attempt=2)
    with pytest.raises(GithubActionRejectedError):
        provider.execute("rerun_workflow", 10, 1, "a" * 40)
    assert not any(request.url.path.endswith("/rerun") for request in requests)
    provider.close()


def test_expired_deadline_makes_no_request(key):
    requests = []
    provider = client(key, requests)
    with pytest.raises(GithubUnavailableError):
        provider.execute("rerun_workflow", 10, 1, "a" * 40, deadline=monotonic() - 1)
    assert requests == []
    provider.close()
