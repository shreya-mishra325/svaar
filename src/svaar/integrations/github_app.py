"""Read-only GitHub App adapter; synthetic HTTP tests, no automatic startup calls.

Contracts checked 2026-10-26:
https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-json-web-token-jwt-for-a-github-app
https://docs.github.com/en/rest/apps/apps#create-an-installation-access-token-for-an-app
https://docs.github.com/en/rest/actions/workflow-runs#get-a-workflow-run
"""

import base64
import binascii
import re
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from svaar.config import Settings
from svaar.incidents.fingerprints import (
    MAX_ARCHIVE_BYTES,
    LogSignature,
    LogSignatureError,
    signature_from_archive,
)
from svaar.integrations.models import RepoMapping


class GithubUnavailableError(Exception):
    """Sanitized authentication, transport or response failure."""


class _Token(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    token: SecretStr = Field(min_length=1)
    expires_at: datetime


class _Repository(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    id: int = Field(gt=0, strict=True)
    full_name: str


class _Run(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    id: int = Field(gt=0, strict=True)
    repository: _Repository
    status: str
    conclusion: str | None


class _Attempt(_Run):
    run_attempt: int = Field(gt=0, strict=True)
    workflow_id: int = Field(gt=0, strict=True)
    head_sha: str
    head_branch: str


@dataclass(frozen=True)
class WorkflowRun:
    """Minimal read result; never a new observed event or recovery decision."""

    id: int
    repository_id: int
    status: str
    conclusion: str | None


def load_rsa_key(encoded: SecretStr) -> RSAPrivateKey:
    """Decode configured key without exposing it in errors."""
    try:
        raw = base64.b64decode(encoded.get_secret_value(), validate=True)
        key = serialization.load_pem_private_key(raw, password=None)
        if not isinstance(key, RSAPrivateKey) or key.key_size < 2048:
            raise ValueError("RSA key required")
        return key
    except (ValueError, TypeError, binascii.Error):
        raise ValueError(
            "Configure a base64-encoded RSA private key of at least 2048 bits"
        ) from None


class GithubAppClient:
    """One approved installation/repository; read-only permissions, no redirects/retries."""

    def __init__(
        self,
        *,
        app_id: int,
        private_key_b64: SecretStr,
        installation_id: int,
        repository_id: int,
        transport: httpx.BaseTransport | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if any(
            type(value) is not int or value <= 0
            for value in (app_id, installation_id, repository_id)
        ):
            raise ValueError("Positive GitHub identifiers are required")
        self._key = load_rsa_key(private_key_b64)
        self._app_id, self._installation_id = app_id, installation_id
        self._repository_id = repository_id
        self._now = now
        self._token: _Token | None = None
        self._lock = threading.Lock()
        self._transport = transport
        self._http = httpx.Client(
            base_url="https://api.github.com/",
            headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10"},
            timeout=httpx.Timeout(6, connect=2),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    @classmethod
    def for_repository(
        cls,
        session: Session,
        settings: Settings,
        org_id: uuid.UUID,
        repository_id: int,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> "GithubAppClient":
        """Resolve only an explicit same-org mapping; no default/latest organization."""
        mapping = session.scalar(
            select(RepoMapping).where(
                RepoMapping.org_id == org_id,
                RepoMapping.repository_id == repository_id,
            )
        )
        if mapping is None:
            raise GithubUnavailableError("GitHub repository is not mapped")
        if settings.github_app_id is None or settings.github_private_key_b64 is None:
            raise GithubUnavailableError("GitHub App is not configured")
        return cls(
            app_id=settings.github_app_id,
            private_key_b64=settings.github_private_key_b64,
            installation_id=mapping.installation_id,
            repository_id=mapping.repository_id,
            transport=transport,
        )

    def close(self) -> None:
        """Release resources and cached credentials."""
        self._token = None
        self._http.close()

    def _request(self, method: str, path: str, token: str, *, body: dict | None = None) -> dict:
        try:
            with self._http.stream(
                method, path, headers={"Authorization": "Bearer " + token}, json=body
            ) as response:
                expected = 201 if method == "POST" else 200
                if response.status_code != expected:
                    raise ValueError("Rejected")
                data = bytearray()
                for chunk in response.iter_bytes():
                    if len(data) + len(chunk) > 1024 * 1024:
                        raise ValueError("Response limit")
                    data.extend(chunk)
                import json

                parsed = json.loads(data)
                if not isinstance(parsed, dict):
                    raise ValueError("Invalid response")
                return parsed
        except (httpx.HTTPError, ValueError, RecursionError):
            raise GithubUnavailableError("GitHub request could not be verified") from None

    def _access_token(self) -> str:
        with self._lock:
            now = self._now()
            if now.tzinfo is None:
                raise GithubUnavailableError("A timezone-aware clock is required")
            if self._token is not None and self._token.expires_at > now + timedelta(minutes=5):
                return self._token.token.get_secret_value()
            self._token = None
            try:
                signed = jwt.encode(
                    {
                        "iss": str(self._app_id),
                        "iat": int(now.timestamp()) - 60,
                        "exp": int(now.timestamp()) + 480,
                    },
                    self._key,
                    algorithm="RS256",
                )
                token = _Token.model_validate(
                    self._request(
                        "POST",
                        f"app/installations/{self._installation_id}/access_tokens",
                        signed,
                        body={
                            "repository_ids": [self._repository_id],
                            "permissions": {"actions": "read", "metadata": "read"},
                        },
                    )
                )
                if token.expires_at.tzinfo is None or token.expires_at <= now:
                    raise ValueError("Expired token")
            except (ValueError, jwt.PyJWTError):
                raise GithubUnavailableError(
                    "GitHub authentication could not be verified"
                ) from None
            self._token = token
            return token.token.get_secret_value()

    def repository_name(self) -> str:
        """Read canonical repository identity using the fixed numeric repository ID."""
        try:
            result = _Repository.model_validate(
                self._request(
                    "GET",
                    f"repositories/{self._repository_id}",
                    self._access_token(),
                )
            )
            if (
                result.id != self._repository_id
                or re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", result.full_name) is None
                or any(part in {".", ".."} for part in result.full_name.split("/"))
            ):
                raise ValueError("Repository mismatch")
        except ValueError:
            raise GithubUnavailableError("GitHub repository could not be verified") from None
        return result.full_name

    def workflow_run(self, run_id: int) -> WorkflowRun:
        """GET one run; verify the run and nested repository identities before returning."""
        if type(run_id) is not int or run_id <= 0:
            raise ValueError("Positive run ID required")
        name = self.repository_name()
        try:
            result = _Run.model_validate(
                self._request(
                    "GET",
                    f"repos/{name}/actions/runs/{run_id}",
                    self._access_token(),
                )
            )
            if result.id != run_id or result.repository.id != self._repository_id:
                raise ValueError("Run mismatch")
        except ValueError:
            raise GithubUnavailableError("GitHub workflow run could not be verified") from None
        return WorkflowRun(result.id, result.repository.id, result.status, result.conclusion)

    def workflow_log_signature(self, run_id: int) -> LogSignature:
        """Follow one authenticated log redirect using a separate credential-free client.

        https://docs.github.com/en/rest/actions/workflow-runs#download-workflow-run-logs
        Only documented Actions storage hosts are accepted. No automatic redirects,
        GitHub credentials, API headers or API cookies reach the storage request.
        """
        run = self.workflow_run(run_id)
        if run.status != "completed" or run.conclusion not in {
            "failure",
            "timed_out",
            "startup_failure",
        }:
            raise GithubUnavailableError("Completed failed workflow logs are required")
        name = self.repository_name()
        return self._log_signature(f"repos/{name}/actions/runs/{run_id}/logs")

    def workflow_attempt_signature(
        self,
        run_id: int,
        attempt: int,
        *,
        head_sha: str,
        workflow_id: int,
        branch: str,
    ) -> LogSignature:
        """Match immutable observed attempt metadata before reading its specific logs."""
        if type(run_id) is not int or run_id <= 0 or type(attempt) is not int or attempt <= 0:
            raise ValueError("Positive run and attempt required")
        name = self.repository_name()
        path = f"repos/{name}/actions/runs/{run_id}/attempts/{attempt}"
        try:
            result = _Attempt.model_validate(self._request("GET", path, self._access_token()))
            if (
                result.id != run_id
                or result.repository.id != self._repository_id
                or result.run_attempt != attempt
                or result.head_sha != head_sha
                or result.workflow_id != workflow_id
                or result.head_branch != branch
                or result.status != "completed"
                or result.conclusion not in {"failure", "timed_out", "startup_failure"}
            ):
                raise ValueError("Attempt mismatch")
        except ValueError:
            raise GithubUnavailableError("GitHub workflow attempt could not be verified") from None
        return self._log_signature(path + "/logs")

    def _log_signature(self, path: str) -> LogSignature:
        """Download one bounded signed archive; never forward API credentials."""
        try:
            with self._http.stream(
                "GET",
                path,
                headers={"Authorization": "Bearer " + self._access_token()},
            ) as response:
                locations = response.headers.get_list("location")
                if response.status_code != 302 or len(locations) != 1:
                    raise ValueError("Log redirect required")
                url = httpx.URL(locations[0])
                if (
                    url.scheme != "https"
                    or url.port not in {None, 443}
                    or url.userinfo
                    or url.fragment
                    or not (
                        url.host == "results-receiver.actions.githubusercontent.com"
                        or bool(re.fullmatch(r"[a-z0-9]+\.blob\.core\.windows\.net", url.host))
                    )
                ):
                    raise ValueError("Untrusted archive location")
            with httpx.Client(
                timeout=httpx.Timeout(6, connect=2),
                follow_redirects=False,
                trust_env=False,
                transport=self._transport,
            ) as download:
                with download.stream("GET", url) as response:
                    if response.status_code != 200:
                        raise ValueError("Download rejected")
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        if len(data) + len(chunk) > MAX_ARCHIVE_BYTES:
                            raise ValueError("Archive limit")
                        data.extend(chunk)
            return signature_from_archive(bytes(data))
        except (httpx.HTTPError, httpx.InvalidURL, ValueError, LogSignatureError):
            raise GithubUnavailableError("GitHub workflow logs could not be verified") from None
