"""Application factory and lifecycle composition; feature logic belongs in modules."""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from svaar.actions.catalog import build_registry
from svaar.actions.dispatcher import ApprovalPolicy, Dispatcher
from svaar.agent.llm import HttpChatModel
from svaar.agent.loop import AgentLoop
from svaar.agent.notifications import (
    enqueue_call_failure,
    enqueue_claim_check_failure,
    enqueue_voice_fallback,
)
from svaar.agent.runtime import ChatRuntime
from svaar.agent.voice_runner import VoiceAgentExecutor
from svaar.api.errors import ErrorResponse, install_error_handlers
from svaar.api.health import router as health_router
from svaar.api.router import api_router
from svaar.config import Settings
from svaar.db import create_database_engine
from svaar.decisions.classifier import StructuredClassifier
from svaar.decisions.service import DecisionService
from svaar.incidents.claim_checks import claim_check_authorized
from svaar.incidents.service import escalation_authorized
from svaar.integrations.ci_actions import CiActionService
from svaar.logging import configure_logging
from svaar.voice.calls import (
    CallService,
    prepare_claim_check_call,
    prepare_phone_verification_call,
)
from svaar.voice.contracts import TurnRunner
from svaar.voice.provider import VoiceProvider
from svaar.voice.runtime import VoiceRuntime
from svaar.voice.status import router as voice_status_router

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, *, status_ingress: bool = False) -> FastAPI:
    """Build an independent application with lifespan-owned database resources."""
    settings = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level)
        engine = create_database_engine(settings)
        app.state.engine = engine
        app.state.session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        model = None
        loop = None
        logger.info("application_started")
        try:
            if settings.llm_model is not None and not status_ingress:
                model = HttpChatModel.from_settings(settings)
                dispatcher = Dispatcher(
                    build_registry(
                        ci_actions=CiActionService.from_settings(
                            app.state.session_factory, settings
                        ).execute
                        if settings.github_actions_enabled
                        else None,
                        prepare_claim_call=prepare_claim_check_call,
                    ),
                    ApprovalPolicy.from_settings(settings),
                )
                loop = AgentLoop(
                    model,
                    dispatcher,
                    DecisionService.from_settings(
                        StructuredClassifier(model.classify, model_version=settings.llm_model)
                        if settings.classifier_enabled
                        else None,
                        settings,
                    ),
                )
            app.state.agent_loop = loop
            app.state.chat_runtime = (
                ChatRuntime(
                    app.state.session_factory,
                    loop,
                    prepare_phone_call=prepare_phone_verification_call,
                )
                if loop is not None
                else None
            )
            runner: TurnRunner | None = (
                VoiceRuntime(
                    app.state.session_factory,
                    VoiceAgentExecutor(loop),
                    notify_failure=enqueue_voice_fallback,
                )
                if loop is not None
                else None
            )
            app.state.voice_turn_runner = runner
            yield
        finally:
            try:
                if loop is not None:
                    loop.close()
                if model is not None:
                    await run_in_threadpool(model.close)
            finally:
                if hasattr(app.state, "voice_turn_runner"):
                    del app.state.voice_turn_runner
                if hasattr(app.state, "chat_runtime"):
                    del app.state.chat_runtime
                if hasattr(app.state, "agent_loop"):
                    del app.state.agent_loop
                await run_in_threadpool(engine.dispose)
                del app.state.session_factory
                del app.state.engine
                logger.info("application_stopped")

    app = FastAPI(
        title="Svaar",
        version="0.1.0",
        lifespan=lifespan,
        debug=False,
        docs_url="/docs" if settings.environment != "production" and not status_ingress else None,
        redoc_url=None,
        openapi_url=(
            "/openapi.json" if settings.environment != "production" and not status_ingress else None
        ),
        redirect_slashes=not status_ingress,
        responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    )
    app.state.cloudflare_status_ingress = status_ingress
    app.state.voice_failure_notifier = enqueue_call_failure
    app.state.voice_requester_notifier = enqueue_claim_check_failure
    app.state.settings = settings
    install_error_handlers(app)
    if status_ingress:
        app.include_router(voice_status_router, prefix="/api/v1")
    else:
        app.include_router(health_router)
        app.include_router(api_router)
    return app


def create_status_ingress(settings: Settings | None = None) -> FastAPI:
    """Cloudflare-only status listener: bind 127.0.0.1 with proxy headers disabled.

    The local host and its cloudflared process are trusted. This factory must not
    serve direct public traffic or sit behind an arbitrary local proxy.
    """
    settings = settings if settings is not None else Settings()
    if settings.voice_status_secret is None:
        raise ValueError("Configure a separate voice status secret before starting ingress")
    return create_app(settings, status_ingress=True)


def create_call_service(
    sessions: sessionmaker[Session],
    provider: VoiceProvider,
    settings: Settings,
    *,
    ready: Callable[[], bool] | None = None,
) -> CallService:
    """Compose every dispatch-time guard for live placement.

    Escalation and claim checks are rechecked against current incident and claim
    state, calls per recipient are capped and an optional readiness probe runs
    first. No route, job or model tool invokes placement; callers stay explicit.
    """
    return CallService(
        sessions,
        provider,
        escalation_authorized=escalation_authorized,
        claim_check_authorized=claim_check_authorized,
        daily_limit=settings.voice_daily_call_limit,
        ready=ready,
    )
