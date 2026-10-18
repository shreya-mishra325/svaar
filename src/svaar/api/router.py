"""Mount future feature routers here under the stable /api/v1 prefix."""

from fastapi import APIRouter

api_router = APIRouter(prefix="/api/v1")
