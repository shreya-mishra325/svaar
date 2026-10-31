"""Render-only public routes, with an explicit managed-edge trust policy.

Render documents that its Cloudflare edge overwrites CF-Connecting-IP. This
factory is only for a public Render web service, never a generic reverse proxy.
https://render.com/articles/host-pocketbase-on-render
"""

from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

from svaar.api.health import router as health_router
from svaar.app import create_app
from svaar.config import Settings
from svaar.integrations.routes import github_webhook
from svaar.render_start import render_hostname


def create_render_app(settings: Settings | None = None) -> FastAPI:
    """Keep docs/operator routes absent; reuse existing voice auth and call resolver."""
    hostname = render_hostname()
    settings = settings if settings is not None else Settings(_env_file=None)
    if (
        settings.environment != "production"
        or settings.voice_turn_mode != "llm_endpoint"
        or settings.voice_status_secret is None
        or settings.voice_turn_token is None
    ):
        raise ValueError("Render requires production custom-LLM mode and separate voice tokens")
    app = create_app(settings, status_ingress=True)
    # Do not pretend Render's reverse proxy is a loopback Cloudflare sidecar.
    app.state.cloudflare_status_ingress = False
    app.state.render_status_ingress = True
    app.add_api_route("/api/v1/webhooks/github", github_webhook, methods=["POST"])
    app.include_router(health_router)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[hostname])
    return app
