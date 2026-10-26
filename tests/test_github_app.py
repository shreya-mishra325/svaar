"""GitHub App contracts with synthetic RSA keys and mocked HTTP only."""

import base64
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from factories import make_org
from pydantic import SecretStr, ValidationError

from svaar.config import Settings
from svaar.integrations.github_app import GithubAppClient, GithubUnavailableError
from svaar.integrations.models import RepoMapping

NOW = datetime(2026, 10, 26, tzinfo=UTC)


@pytest.fixture(scope="module")
def key():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    encoded = base64.b64encode(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    ).decode()
    return private, encoded


def make_client(key, handler, now=lambda: NOW):
    return GithubAppClient(
        app_id=7,
        private_key_b64=SecretStr(key[1]),
        installation_id=8,
        repository_id=9,
        transport=httpx.MockTransport(handler),
        now=now,
    )


def handler(key, requests, *, change=None):
    def handle(request):
        requests.append(request)
        assert request.url.host == "api.github.com"
        assert request.headers["X-GitHub-Api-Version"] == "2026-03-10"
        if request.method == "POST":
            assert request.url.path == "/app/installations/8/access_tokens"
            claims = jwt.decode(
                request.headers["Authorization"].removeprefix("Bearer "),
                key[0].public_key(),
                algorithms=["RS256"],
                options={"verify_exp": False, "verify_iat": False},
            )
            assert claims == {
                "iss": "7",
                "iat": int(NOW.timestamp()) - 60,
                "exp": int(NOW.timestamp()) + 480,
            }
            assert json.loads(request.content) == {
                "repository_ids": [9],
                "permissions": {"actions": "read", "metadata": "read"},
            }
            expiry = NOW + timedelta(hours=1)
            if change == "expiry":
                expiry = NOW - timedelta(seconds=1)
            if change == "http":
                return httpx.Response(401, text="private-provider-error")
            return httpx.Response(
                201,
                json={
                    "token": "private-installation-token",
                    "expires_at": expiry.isoformat(),
                },
            )
        assert request.headers["Authorization"] == "Bearer private-installation-token"
        if change == "redirect":
            return httpx.Response(302, headers={"Location": "https://other.example/private"})
        if change == "oversize":
            return httpx.Response(200, content=b"x" * (1024 * 1024 + 1))
        if change == "json":
            return httpx.Response(200, text="private-invalid-json")
        if request.url.path == "/repositories/9":
            return httpx.Response(
                200,
                json={
                    "id": 10 if change == "repo" else 9,
                    "full_name": "../repo" if change == "path" else "team/repo",
                },
            )
        assert request.url.path == "/repos/team/repo/actions/runs/10"
        return httpx.Response(
            200,
            json={
                "id": 11 if change == "run" else 10,
                "repository": {"id": 11 if change == "run_repo" else 9, "full_name": "team/repo"},
                "status": "completed",
                "conclusion": "failure",
                "private": "discarded-payload",
            },
        )

    return handle


def test_jwt_scoped_token_and_read_contract(key):
    requests = []
    client = make_client(key, handler(key, requests))
    try:
        assert not requests
        result = client.workflow_run(10)
        assert result.id == 10 and result.repository_id == 9 and result.conclusion == "failure"
        assert "private" not in repr(result)
        client.workflow_run(10)
        assert sum(request.method == "POST" for request in requests) == 1
    finally:
        client.close()


@pytest.mark.parametrize(
    "change", ["expiry", "http", "redirect", "oversize", "json", "repo", "path", "run", "run_repo"]
)
def test_failures_are_sanitized_and_never_retried(key, change):
    requests = []
    client = make_client(key, handler(key, requests, change=change))
    try:
        with pytest.raises(GithubUnavailableError) as exc:
            client.workflow_run(10)
        assert "private" not in str(exc.value)
        assert sum(request.method == "POST" for request in requests) == 1
        assert len(requests) <= 3
    finally:
        client.close()


def test_expiry_margin_refreshes_without_reusing_expiring_token(key):
    clock = [NOW]
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            201,
            json={
                "token": "private-token",
                "expires_at": (clock[0] + timedelta(hours=1)).isoformat(),
            },
        )

    client = make_client(key, handle, now=lambda: clock[0])
    try:
        client._access_token()
        clock[0] += timedelta(minutes=54)
        client._access_token()
        assert len(requests) == 1
        clock[0] += timedelta(minutes=1)
        client._access_token()
        assert len(requests) == 2
    finally:
        client.close()


def test_concurrent_reads_share_one_token_exchange(key):
    requests = []
    barrier = threading.Barrier(2)
    client = make_client(key, handler(key, requests))
    try:

        def read(_):
            barrier.wait(timeout=3)
            return client.workflow_run(10).id

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(read, range(2))) == [10, 10]
        assert sum(request.method == "POST" for request in requests) == 1
    finally:
        client.close()


def test_timeout_has_no_retry(key):
    requests = []

    def fail(request):
        requests.append(request)
        raise httpx.ReadTimeout("private-timeout")

    client = make_client(key, fail)
    try:
        with pytest.raises(GithubUnavailableError, match="could not be verified"):
            client.workflow_run(10)
        assert len(requests) == 1
    finally:
        client.close()


@pytest.mark.parametrize("run_id", [0, -1, True, "10"])
def test_invalid_run_never_reaches_http(key, run_id):
    client = make_client(key, lambda _: pytest.fail("Invalid input reached HTTP"))
    try:
        with pytest.raises(ValueError):
            client.workflow_run(run_id)
    finally:
        client.close()


def test_settings_pair_and_private_key_validation(settings, key):
    config = Settings(
        _env_file=None,
        database_url=settings.database_url,
        github_app_id=7,
        github_private_key_b64=key[1],
    )
    assert key[1] not in repr(config)
    for kwargs in [
        {"github_app_id": 7},
        {"github_private_key_b64": key[1]},
        {"github_app_id": 7, "github_private_key_b64": "private-invalid"},
    ]:
        with pytest.raises(ValidationError) as exc:
            Settings(_env_file=None, database_url=settings.database_url, **kwargs)
        assert "private-invalid" not in str(exc.value)


def test_org_mapping_is_required_before_client_construction(db_session, settings, key):
    org, other = make_org(db_session), make_org(db_session)
    db_session.add(RepoMapping(org_id=org.id, repository_id=9, installation_id=8))
    db_session.flush()
    config = Settings(
        _env_file=None,
        database_url=settings.database_url,
        github_app_id=7,
        github_private_key_b64=key[1],
    )
    with pytest.raises(GithubUnavailableError, match="not mapped"):
        GithubAppClient.for_repository(db_session, config, other.id, 9)
    with pytest.raises(GithubUnavailableError, match="not mapped"):
        GithubAppClient.for_repository(db_session, config, org.id, 10)
    requests = []
    client = GithubAppClient.for_repository(
        db_session,
        config,
        org.id,
        9,
        transport=httpx.MockTransport(lambda request: requests.append(request)),
    )
    client.close()
    assert not requests


@pytest.mark.parametrize(
    "change",
    [
        None,
        "http-url",
        "local",
        "userinfo",
        "suffix",
        "second-redirect",
        "oversize",
        "invalid-archive",
    ],
)
def test_workflow_logs_isolate_credentials_and_bound_redirects(key, change):
    from test_failure_fingerprints import archive

    from svaar.incidents.fingerprints import MAX_ARCHIVE_BYTES

    requests = []
    base = handler(key, requests)
    downloads = []
    url = "https://productionresultssa8.blob.core.windows.net/logs?private-signed-value"
    if change == "http-url":
        url = url.replace("https:", "http:")
    elif change == "local":
        url = "https://127.0.0.1/private"
    elif change == "userinfo":
        url = "https://user:secret@productionresultssa8.blob.core.windows.net/logs"
    elif change == "suffix":
        url = "https://productionresultssa8.blob.core.windows.net.evil.example/logs"

    def handle(request):
        if request.url.path.endswith("/logs") and request.url.host == "api.github.com":
            assert request.headers["Authorization"] == "Bearer private-installation-token"
            return httpx.Response(
                302,
                headers={
                    "Location": url,
                    "Set-Cookie": "private-api-cookie=secret",
                },
            )
        if request.url.host != "api.github.com":
            downloads.append(request)
            assert "authorization" not in request.headers
            assert "cookie" not in request.headers
            assert "x-github-api-version" not in request.headers
            if change == "second-redirect":
                return httpx.Response(302, headers={"Location": "https://evil.example/"})
            if change == "oversize":
                return httpx.Response(200, content=b"x" * (MAX_ARCHIVE_BYTES + 1))
            return httpx.Response(
                200,
                content=(
                    b"private-invalid-archive"
                    if change == "invalid-archive"
                    else archive([("job.txt", "synthetic compile error 17")])
                ),
            )
        return base(request)

    client = make_client(key, handle)
    try:
        if change:
            with pytest.raises(GithubUnavailableError) as exc:
                client.workflow_log_signature(10)
            assert "private" not in str(exc.value)
        else:
            result = client.workflow_log_signature(10)
            assert result.file_count == 1 and len(result.digest) == 64
        assert len(downloads) == (0 if change in {"http-url", "local", "userinfo", "suffix"} else 1)
    finally:
        client.close()


def test_nonfailed_run_never_downloads_logs(key):
    requests = []
    base = handler(key, requests)

    def handle(request):
        response = base(request)
        if request.url.path == "/repos/team/repo/actions/runs/10":
            body = response.json()
            body["conclusion"] = "success"
            return httpx.Response(200, json=body)
        return response

    client = make_client(key, handle)
    try:
        with pytest.raises(GithubUnavailableError, match="Completed failed"):
            client.workflow_log_signature(10)
        assert not any(request.url.path.endswith("/logs") for request in requests)
    finally:
        client.close()


@pytest.mark.parametrize("change", [None, "attempt", "sha", "workflow", "branch"])
def test_attempt_log_download_checks_observed_metadata(key, change):
    from test_failure_fingerprints import archive

    requests, archives = [], []
    base = handler(key, requests)

    def handle(request):
        if request.url.path == "/repos/team/repo/actions/runs/10/attempts/2":
            return httpx.Response(
                200,
                json={
                    "id": 10,
                    "repository": {"id": 9, "full_name": "team/repo"},
                    "status": "completed",
                    "conclusion": "failure",
                    "run_attempt": 3 if change == "attempt" else 2,
                    "workflow_id": 99 if change == "workflow" else 55,
                    "head_sha": "b" * 40 if change == "sha" else "a" * 40,
                    "head_branch": "other" if change == "branch" else "main",
                },
            )
        if request.url.path == "/repos/team/repo/actions/runs/10/attempts/2/logs":
            return httpx.Response(
                302,
                headers={
                    "Location": "https://productionresultssa8.blob.core.windows.net/logs",
                },
            )
        if request.url.host.endswith(".blob.core.windows.net"):
            archives.append(request)
            assert "authorization" not in request.headers
            return httpx.Response(200, content=archive([("job.txt", "error 17")]))
        return base(request)

    client = make_client(key, handle)
    try:
        if change:
            with pytest.raises(GithubUnavailableError, match="attempt could not be verified"):
                client.workflow_attempt_signature(
                    10, 2, head_sha="a" * 40, workflow_id=55, branch="main"
                )
            assert not archives
        else:
            assert (
                client.workflow_attempt_signature(
                    10, 2, head_sha="a" * 40, workflow_id=55, branch="main"
                ).file_count
                == 1
            )
            assert len(archives) == 1
    finally:
        client.close()
