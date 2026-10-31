"""leased CI enrichment jobs

Revision ID: 0020
Revises: 0019
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | Sequence[str] | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this schema change."""
    op.create_table(
        "ci_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column("owner_principal_id", sa.Uuid(), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column(
            "next_check_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(state = 'running' AND lease_token IS NOT NULL AND lease_until IS NOT NULL) "
            "OR (state <> 'running' AND lease_token IS NULL AND lease_until IS NULL)",
            name=op.f("ck_ci_jobs_lease_valid"),
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'running', 'done', 'failed')", name=op.f("ck_ci_jobs_state_valid")
        ),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_ci_jobs_attempts_valid")),
        sa.ForeignKeyConstraint(
            ["event_id"], ["events.id"], name=op.f("fk_ci_jobs_event_id_events")
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_ci_jobs_org_id_orgs")),
        sa.ForeignKeyConstraint(
            ["owner_principal_id"],
            ["principals.id"],
            name=op.f("fk_ci_jobs_owner_principal_id_principals"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ci_jobs")),
        sa.UniqueConstraint("event_id", name=op.f("uq_ci_jobs_event_id")),
    )
    op.create_index(
        "ix_ci_jobs_due", "ci_jobs", ["state", "next_check_at", "lease_until"], unique=False
    )


def downgrade() -> None:
    """Refuse deletion of pending work and its retry/lease audit."""
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM ci_jobs)")):
        raise RuntimeError("Cannot downgrade with CI jobs present")

    op.drop_index("ix_ci_jobs_due", table_name="ci_jobs")
    op.drop_table("ci_jobs")
