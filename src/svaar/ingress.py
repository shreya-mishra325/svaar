"""Restricted local demo origin for a named Cloudflare Tunnel.

Run on 127.0.0.1 in the same network namespace as cloudflared, with proxy headers
disabled. Never publish this listener's port or reuse this trust boundary behind
an arbitrary reverse proxy.
"""

from fastapi import FastAPI
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from svaar.api.health import router as health_router
from svaar.app import create_status_ingress
from svaar.config import Settings
from svaar.integrations.routes import github_webhook


class LoopbackOnly:
    """Trust the dedicated tunnel sidecar only; ignore forwarded peer assertions."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and (
            not scope.get("client") or scope["client"][0] != "127.0.0.1"
        ):
            await Response(status_code=403)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_demo_ingress(settings: Settings | None = None) -> FastAPI:
    """Mount only provider routes and minimal probes, never the operator router."""
    app = create_status_ingress(settings)
    app.add_api_route("/api/v1/webhooks/github", github_webhook, methods=["POST"])
    app.include_router(health_router)
    app.add_middleware(LoopbackOnly)
    return app
