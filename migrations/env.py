"""Use Svaar settings and metadata for online and offline migrations."""

from alembic import context

from svaar.config import Settings
from svaar.db import Base, create_database_engine
from svaar.logging import configure_logging

# Import future feature model modules here so autogenerate sees their tables.
target_metadata = Base.metadata


def run_migrations_offline(settings: Settings) -> None:
    """Render SQL without connecting to a database."""
    context.configure(
        url=settings.database_url.get_secret_value(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online(settings: Settings) -> None:
    """Run schema changes in a transaction and always dispose the engine."""
    engine = create_database_engine(settings)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection, target_metadata=target_metadata, compare_type=True
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


settings = Settings()
configure_logging(settings.log_level)
if context.is_offline_mode():
    run_migrations_offline(settings)
else:
    run_migrations_online(settings)
