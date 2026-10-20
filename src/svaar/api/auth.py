"""Operator bearer authentication; voice, channel and webhook routes use their own."""

import hmac

from fastapi import HTTPException, Request
from fastapi.security.utils import get_authorization_scheme_param


def require_operator(request: Request) -> None:
    """Accept only the configured operator token, compared in constant time.

    Raises:
        HTTPException: 503 when no operator token is configured, 401 otherwise.
    """
    token = request.app.state.settings.operator_token
    if token is None:
        raise HTTPException(503)
    scheme, credential = get_authorization_scheme_param(request.headers.get("Authorization"))
    expected = token.get_secret_value().encode()
    if scheme.lower() != "bearer" or not hmac.compare_digest(credential.encode(), expected):
        raise HTTPException(401, headers={"WWW-Authenticate": "Bearer"})
