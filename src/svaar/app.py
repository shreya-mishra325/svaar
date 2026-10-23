"""Application factory and lifecycle composition; feature logic belongs in modules."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker
from starlette.concurrency import run_in_threadpool

from svaar.actions.catalog import build_registry
from svaar.actions.dispatcher import ApprovalPolicy, Dispatcher
from svaar.agent.llm import HttpChatModel
from svaar.agent.loop import AgentLoop
from svaar.agent.runtime import ChatRuntime
from svaar.api.errors import ErrorResponse, install_error_handlers
from svaar.api.health import router as health_router
from svaar.api.router import api_router
from svaar.config import Settings
from svaar.db import create_database_engine
from svaar.decisions.service import DecisionService
from svaar.logging import configure_logging

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
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
            if settings.llm_model is not None:
                model = HttpChatModel.from_settings(settings)
                dispatcher = Dispatcher(build_registry(), ApprovalPolicy.from_settings(settings))
                loop = AgentLoop(model, dispatcher, DecisionService.from_settings(None, settings))
            app.state.agent_loop = loop
            app.state.chat_runtime = (
                ChatRuntime(app.state.session_factory, loop) if loop is not None else None
            )
            yield
        finally:
            try:
                if loop is not None:
                    loop.close()
                if model is not None:
                    await run_in_threadpool(model.close)
            finally:
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
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.environment != "production" else None,
        responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    )
    app.state.settings = settings
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(api_router)
    return app
