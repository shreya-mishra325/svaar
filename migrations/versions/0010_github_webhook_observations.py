"""github webhook observations

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this schema change."""
    op.create_table(
        "events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("external_key", sa.String(length=255), nullable=False),
        sa.Column("source_delivery_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_events_org_id_orgs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
        sa.UniqueConstraint("source", "external_key", name="uq_events_source_external_key"),
    )
    op.create_index(op.f("ix_events_org_id"), "events", ["org_id"], unique=False)
    op.create_table(
        "repo_mappings",
        sa.Column("repository_id", sa.BigInteger(), nullable=False),
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "repository_id > 0 AND installation_id > 0", name=op.f("ck_repo_mappings_ids_valid")
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_repo_mappings_org_id_orgs")),
        sa.PrimaryKeyConstraint("repository_id", name=op.f("pk_repo_mappings")),
    )
    op.create_index(op.f("ix_repo_mappings_org_id"), "repo_mappings", ["org_id"], unique=False)
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("event_id", sa.Uuid(), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('accepted', 'ignored')", name=op.f("ck_webhook_deliveries_state_valid")
        ),
        sa.ForeignKeyConstraint(
            ["event_id"], ["events.id"], name=op.f("fk_webhook_deliveries_event_id_events")
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["orgs.id"], name=op.f("fk_webhook_deliveries_org_id_orgs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_deliveries")),
    )

    op.execute(
        "CREATE FUNCTION svaar_observed_events_immutable() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN "
        "RAISE EXCEPTION 'Observed events are append-only'; END; $$"
    )
    op.execute(
        "CREATE TRIGGER events_append_only BEFORE UPDATE OR DELETE ON events "
        "FOR EACH ROW EXECUTE FUNCTION svaar_observed_events_immutable()"
    )


def downgrade() -> None:
    """Reverse this schema change."""
    op.drop_table("webhook_deliveries")
    op.drop_index(op.f("ix_repo_mappings_org_id"), table_name="repo_mappings")
    op.drop_table("repo_mappings")
    op.drop_index(op.f("ix_events_org_id"), table_name="events")
    op.drop_table("events")

    op.execute("DROP FUNCTION svaar_observed_events_immutable()")
