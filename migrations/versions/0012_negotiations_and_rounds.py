"""Negotiations with their constraint snapshot, and one row per validated round.

Revision ID: 0012
Revises: 0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this schema change."""
    op.create_table(
        "negotiations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=True),
        sa.Column("constraints", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("initial_proposal", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("accepted_proposal", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('accepted', 'rejected')", name=op.f("ck_negotiations_state_valid")
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"], ["incidents.id"], name=op.f("fk_negotiations_incident_id_incidents")
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_negotiations_org_id_orgs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_negotiations")),
    )
    op.create_index(
        op.f("ix_negotiations_incident_id"), "negotiations", ["incident_id"], unique=False
    )
    op.create_index(op.f("ix_negotiations_org_id"), "negotiations", ["org_id"], unique=False)
    op.create_table(
        "negotiation_rounds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("negotiation_id", sa.Uuid(), nullable=False),
        sa.Column("round_index", sa.Integer(), nullable=False),
        sa.Column("proposal", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("revised_by", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("valid", sa.Boolean(), nullable=False),
        sa.Column("violations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["negotiation_id"],
            ["negotiations.id"],
            name=op.f("fk_negotiation_rounds_negotiation_id_negotiations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_negotiation_rounds")),
        sa.UniqueConstraint("negotiation_id", "round_index", name="uq_negotiation_rounds_index"),
    )
    op.create_index(
        op.f("ix_negotiation_rounds_negotiation_id"),
        "negotiation_rounds",
        ["negotiation_id"],
        unique=False,
    )


def downgrade() -> None:
    """Reverse this schema change."""
    op.drop_index(op.f("ix_negotiation_rounds_negotiation_id"), table_name="negotiation_rounds")
    op.drop_table("negotiation_rounds")
    op.drop_index(op.f("ix_negotiations_org_id"), table_name="negotiations")
    op.drop_index(op.f("ix_negotiations_incident_id"), table_name="negotiations")
    op.drop_table("negotiations")
