"""Gateway composition, infrastructure check and persisted runtime health.

Normal startup requires complete configuration. Caspian private sender addresses
are trusted under the approved MVP policy; invites still control enrollment.
"""

import argparse
import json
import logging
import signal
import threading
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from svaar.actions.catalog import build_registry
from svaar.actions.dispatcher import ApprovalPolicy, Dispatcher
from svaar.agent.caspian import CaspianTelegramTransport
from svaar.agent.llm import HttpChatModel
from svaar.agent.loop import AgentLoop
from svaar.agent.models import GatewayCursor
from svaar.agent.notifications import delivered_incident_alert_at
from svaar.agent.runtime import ChatRuntime
from svaar.agent.transport import TransportUnavailableError
from svaar.agent.worker import GatewayWorker, stream_key
from svaar.config import Settings
from svaar.db import create_database_engine
from svaar.decisions.classifier import StructuredClassifier
from svaar.decisions.service import DecisionService
from svaar.integrations.ci_actions import CiActionService
from svaar.jobs.claim_checks import ClaimAnswerWorker
from svaar.jobs.escalation import EscalationWorker
from svaar.logging import configure_logging
from svaar.voice.calls import (
    claim_check_outcome,
    prepare_claim_check_call,
    prepare_escalation_call,
    prepare_phone_verification_call,
)

logger = logging.getLogger(__name__)


def _periodic(*workers: object) -> Callable[[], None] | None:
    """Run each enabled worker independently; one failure never skips the next."""
    enabled = [worker for worker in workers if worker is not None]
    if not enabled:
        return None

    def run() -> None:
        for worker in enabled:
            try:
                worker.run_once()
            except Exception as exc:
                logger.error("gateway_jobs_failed", extra={"error_type": type(exc).__name__})

    return run


def _run(settings: Settings) -> int:
    if settings.channel_transport != "caspian" or settings.llm_model is None:
        logger.error("gateway_configuration_incomplete; select Caspian and configure the LLM")
        return 2
    with ExitStack() as resources:
        try:
            transport = CaspianTelegramTransport.from_settings(settings)
        except ValueError:
            logger.error("gateway_configuration_incomplete; configure Caspian connection fields")
            return 2
        resources.callback(transport.close)
        engine = create_database_engine(settings)
        resources.callback(engine.dispose)
        sessions = sessionmaker(bind=engine, expire_on_commit=False)
        model = HttpChatModel.from_settings(settings)
        resources.callback(model.close)
        agent = AgentLoop(
            model,
            Dispatcher(
                build_registry(
                    ci_actions=CiActionService.from_settings(sessions, settings).execute
                    if settings.github_actions_enabled
                    else None,
                    prepare_claim_call=prepare_claim_check_call,
                ),
                ApprovalPolicy.from_settings(settings),
            ),
            DecisionService.from_settings(
                StructuredClassifier(model.classify, model_version=settings.llm_model)
                if settings.classifier_enabled
                else None,
                settings,
            ),
        )
        resources.callback(agent.close)
        transport.check_connection()
        runtime = ChatRuntime(sessions, agent, prepare_phone_call=prepare_phone_verification_call)
        jobs = (
            EscalationWorker(
                sessions,
                delivered_alert_at=delivered_incident_alert_at,
                prepare_call=prepare_escalation_call,
                after_seconds=settings.escalation_after_seconds,
                cooldown_seconds=settings.escalation_cooldown_seconds,
                batch_size=settings.escalation_batch_size,
            )
            if settings.escalation_jobs_enabled
            else None
        )
        answers = (
            ClaimAnswerWorker(
                sessions,
                agent.decisions,
                call_outcome=claim_check_outcome,
                batch_size=settings.escalation_batch_size,
            )
            if settings.claim_check_jobs_enabled
            else None
        )
        worker = GatewayWorker(
            sessions,
            runtime,
            transport,
            channel="caspian:telegram",
            connection_id=settings.caspian_telegram_connection_id,
            poll_seconds=settings.gateway_poll_seconds,
            batch_size=settings.gateway_batch_size,
            periodic_jobs=_periodic(jobs, answers),
        )
        stop = threading.Event()
        previous = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
        try:
            for sig in previous:
                signal.signal(sig, lambda *_: stop.set())
            worker.run(stop)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the selected channel or inspect infrastructure/runtime separately."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Database infrastructure only")
    mode.add_argument(
        "--status", action="store_true", help="Persisted runtime heartbeat, no provider call"
    )
    args = parser.parse_args(argv)
    try:
        settings = Settings()
    except ValidationError:
        configure_logging("ERROR")
        logger.error("gateway_configuration_invalid; check SVAAR_ settings")
        return 2
    configure_logging(settings.log_level)
    if not args.check and not args.status:
        try:
            return _run(settings)
        except (SQLAlchemyError, TransportUnavailableError, ValueError) as exc:
            logger.error("gateway_start_failed", extra={"error_type": type(exc).__name__})
            return 1
    if args.status and not settings.caspian_telegram_connection_id:
        print(json.dumps({"status": "not_configured"}))
        return 2
    engine = create_database_engine(settings)
    try:
        if args.check:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            logger.info("gateway_infrastructure_check_passed; channel runtime was not checked")
            return 0
        with sessionmaker(bind=engine)() as session:
            row = session.get(
                GatewayCursor,
                stream_key("caspian:telegram", settings.caspian_telegram_connection_id),
            )
            if row is None:
                print(json.dumps({"status": "not_started"}))
                return 1
            fresh = (datetime.now(UTC) - row.heartbeat_at).total_seconds() <= 60
            status = row.state if fresh else "stale"
            print(json.dumps({"status": status, "error_code": row.error_code}))
            return 0 if fresh and row.state in {"ready", "processing"} else 1
    except SQLAlchemyError as exc:
        logger.error("gateway_database_unavailable", extra={"error_type": type(exc).__name__})
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
