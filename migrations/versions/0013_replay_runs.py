"""Simulated replay results, isolated from observed events.

Revision ID: 0013
Revises: 0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this schema change."""
    op.create_table(
        "replay_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("scenario", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind = 'simulated'", name=op.f("ck_replay_runs_kind_simulated")),
        sa.ForeignKeyConstraint(
            ["incident_id"], ["incidents.id"], name=op.f("fk_replay_runs_incident_id_incidents")
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_replay_runs_org_id_orgs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_replay_runs")),
    )
    op.create_index(
        op.f("ix_replay_runs_incident_id"), "replay_runs", ["incident_id"], unique=False
    )
    op.create_index(op.f("ix_replay_runs_org_id"), "replay_runs", ["org_id"], unique=False)


def downgrade() -> None:
    """Reverse this schema change."""
    op.drop_index(op.f("ix_replay_runs_org_id"), table_name="replay_runs")
    op.drop_index(op.f("ix_replay_runs_incident_id"), table_name="replay_runs")
    op.drop_table("replay_runs")
