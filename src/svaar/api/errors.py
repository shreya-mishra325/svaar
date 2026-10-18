"""Sanitized JSON errors for validation, HTTP failures, and unexpected faults."""

import logging
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

logger = logging.getLogger(__name__)


class ErrorDetail(BaseModel):
    """Machine-readable error code and safe human-readable message."""

    code: str
    message: str
    details: list[dict[str, object]] | None = None


class ErrorResponse(BaseModel):
    """Common error envelope, also used in endpoint response documentation."""

    error: ErrorDetail


def error_response(status: int, code: str, message: str) -> JSONResponse:
    """Construct a minimal error without raw exception text."""
    body = ErrorResponse(error=ErrorDetail(code=code, message=message))
    return JSONResponse(status_code=status, content=body.model_dump(exclude_none=True))


def install_error_handlers(app: FastAPI) -> None:
    """Register handlers without exposing rejected values, bodies, or credentials."""

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"location": list(e["loc"]), "type": e["type"]} for e in exc.errors()]
        body = ErrorResponse(
            error=ErrorDetail(
                code="validation_error", message="Request validation failed", details=details
            )
        )
        return JSONResponse(status_code=422, content=body.model_dump(exclude_none=True))

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        try:
            message = HTTPStatus(exc.status_code).phrase
        except ValueError:
            message = "Request failed"
        response = error_response(exc.status_code, f"http_{exc.status_code}", message)
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error("request_failed", extra={"error_type": type(exc).__name__})
        return error_response(500, "internal_error", "Internal server error")
