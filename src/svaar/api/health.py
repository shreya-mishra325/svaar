"""Unversioned infrastructure probes; neither endpoint changes application state."""

import logging
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from svaar.api.errors import ErrorResponse, error_response

router = APIRouter()
logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    """Minimal probe result."""

    status: Literal["ok", "ready"]


@router.get("/health", response_model=HealthResponse, tags=["infrastructure"])
def health() -> HealthResponse:
    """Report process liveness independently of PostgreSQL availability."""
    return HealthResponse(status="ok")


@router.get(
    "/ready",
    response_model=HealthResponse,
    responses={503: {"model": ErrorResponse}},
    tags=["infrastructure"],
)
def ready(request: Request) -> HealthResponse | JSONResponse:
    """Execute a real query; run synchronous SQL in FastAPI's thread pool."""
    try:
        with request.app.state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.warning("database_unavailable", extra={"error_type": type(exc).__name__})
        return error_response(503, "database_unavailable", "Database is unavailable")
    return HealthResponse(status="ready")
