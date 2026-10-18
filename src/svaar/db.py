"""SQLAlchemy resources shared by infrastructure and future feature modules."""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session

from svaar.config import Settings


class Base(DeclarativeBase):
    """Shared metadata with stable names for future migration constraints."""

    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


def create_database_engine(settings: Settings) -> Engine:
    """Create a lazy pool with bounded connection, checkout, and query waits."""
    url = make_url(settings.database_url.get_secret_value()).set(drivername="postgresql+psycopg")
    timeout = settings.database_timeout_seconds
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_timeout=timeout,
        hide_parameters=True,
        connect_args={
            "connect_timeout": timeout,
            "options": f"-c statement_timeout={timeout * 1000}",
        },
    )


def get_session(request: Request) -> Iterator[Session]:
    """Yield a request-scoped session; callers explicitly commit successful writes."""
    with request.app.state.session_factory() as session:
        yield session
