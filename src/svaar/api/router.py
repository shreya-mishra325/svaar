"""Mount implemented feature routers here under the stable /api/v1 prefix."""

from fastapi import APIRouter

from svaar.identity.routes import router as identity_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(identity_router)
