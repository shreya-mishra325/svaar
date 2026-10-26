"""workflow log signature provenance

Revision ID: 0015
Revises: 0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this schema change."""
    op.create_table(
        "workflow_log_signatures",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.BigInteger(), nullable=False),
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("run_attempt", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.BigInteger(), nullable=False),
        sa.Column("head_sha", sa.String(length=64), nullable=False),
        sa.Column("head_branch", sa.String(length=255), nullable=False),
        sa.Column("algorithm", sa.String(length=32), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "file_count > 0 AND file_count <= 100",
            name=op.f("ck_workflow_log_signatures_files_valid"),
        ),
        sa.CheckConstraint(
            "repository_id > 0 AND run_id > 0 AND run_attempt > 0 AND "
            "workflow_id > 0 AND installation_id > 0",
            name=op.f("ck_workflow_log_signatures_ids_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["event_id"], ["events.id"], name=op.f("fk_workflow_log_signatures_event_id_events")
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["orgs.id"], name=op.f("fk_workflow_log_signatures_org_id_orgs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_log_signatures")),
        sa.UniqueConstraint(
            "org_id",
            "repository_id",
            "run_id",
            "run_attempt",
            "algorithm",
            name="uq_workflow_log_signatures_attempt",
        ),
    )
    op.create_index(
        op.f("ix_workflow_log_signatures_org_id"),
        "workflow_log_signatures",
        ["org_id"],
        unique=False,
    )

    op.execute(
        "CREATE FUNCTION svaar_log_signatures_immutable() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN "
        "RAISE EXCEPTION 'Log signatures are append-only'; END; $$"
    )
    op.execute(
        "CREATE TRIGGER log_signatures_append_only BEFORE UPDATE OR DELETE "
        "ON workflow_log_signatures FOR EACH ROW "
        "EXECUTE FUNCTION svaar_log_signatures_immutable()"
    )


def downgrade() -> None:
    """Reverse this schema change."""
    op.drop_index(op.f("ix_workflow_log_signatures_org_id"), table_name="workflow_log_signatures")
    op.drop_table("workflow_log_signatures")

    op.execute("DROP FUNCTION svaar_log_signatures_immutable()")
