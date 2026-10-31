"""Explicit operator call dispatch; nothing here runs automatically.

Usage:
    python -m svaar.dispatch --list
    python -m svaar.dispatch --place CALL_ID --org ORG_ID
    python -m svaar.dispatch --refresh CALL_ID --org ORG_ID

--place dials a real phone through Bolna. Run it only with explicit authorization
for that call and recipient. Every dispatch-time guard in create_call_service
applies, and Bolna account readiness is checked first. Output never includes
phone numbers, references or credentials.
"""

import argparse
import json
import logging
import uuid
from collections.abc import Callable, Sequence

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from svaar.app import create_call_service
from svaar.config import Settings
from svaar.db import create_database_engine
from svaar.logging import configure_logging
from svaar.voice.bolna import BolnaClient
from svaar.voice.models import VoiceCall

logger = logging.getLogger(__name__)
ProviderFactory = Callable[[Settings], BolnaClient]


def _ready(client: BolnaClient) -> bool:
    return client.readiness().ready


def main(
    argv: Sequence[str] | None = None,
    *,
    provider_factory: ProviderFactory = BolnaClient.from_settings,
    settings_factory: Callable[[], Settings] = Settings,
) -> int:
    """List pending intents, or place/refresh exactly one named call."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true", help="Pending call intents, no phones")
    mode.add_argument("--place", type=uuid.UUID, metavar="CALL_ID", help="Dial one intent")
    mode.add_argument("--refresh", type=uuid.UUID, metavar="CALL_ID", help="Read its receipt")
    parser.add_argument("--org", type=uuid.UUID, help="Organization of the call")
    args = parser.parse_args(argv)
    try:
        settings = settings_factory()
    except ValidationError:
        configure_logging("ERROR")
        logger.error("dispatch_configuration_invalid; check SVAAR_ settings")
        return 2
    configure_logging(settings.log_level)
    engine = create_database_engine(settings)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        if args.list:
            with sessions() as session:
                rows = session.scalars(
                    select(VoiceCall)
                    .where(VoiceCall.state == "pending")
                    .order_by(VoiceCall.created_at)
                    .limit(50)
                ).all()
                print(
                    json.dumps(
                        [
                            {
                                "call_id": str(row.id),
                                "org_id": str(row.org_id),
                                "mission": row.mission,
                                "created_at": row.created_at.isoformat(),
                            }
                            for row in rows
                        ]
                    )
                )
            return 0
        if args.org is None:
            parser.error("--org is required with --place and --refresh")
        try:
            provider = provider_factory(settings)
        except ValueError:
            logger.error("dispatch_provider_not_configured; set Bolna key and agent ID")
            return 2
        try:
            service = create_call_service(
                sessions, provider, settings, ready=lambda: _ready(provider)
            )
            if args.place:
                outcome = service.place(args.org, args.place)
            else:
                outcome = service.refresh(args.org, args.refresh)
        finally:
            provider.close()
        print(json.dumps({"outcome": outcome}))
        return 0 if outcome in {"queued", "active", "closed"} else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
