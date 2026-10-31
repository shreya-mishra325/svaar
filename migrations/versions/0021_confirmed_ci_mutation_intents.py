"""confirmed CI mutation intents

Revision ID: 0021
Revises: 0020
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | Sequence[str] | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this schema change."""
    op.create_table(
        "ci_action_intents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("confirmation_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("repository_id", sa.BigInteger(), nullable=False),
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("run_attempt", sa.Integer(), nullable=False),
        sa.Column("head_sha", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(state = 'accepted' AND status_code IS NOT NULL) "
            "OR (state <> 'accepted' AND status_code IS NULL)",
            name=op.f("ck_ci_action_intents_receipt_valid"),
        ),
        sa.CheckConstraint(
            "action IN ('rerun_workflow', 'cancel_run')",
            name=op.f("ck_ci_action_intents_action_valid"),
        ),
        sa.CheckConstraint(
            "state IN ('placing', 'accepted', 'rejected', 'unknown')",
            name=op.f("ck_ci_action_intents_state_valid"),
        ),
        sa.CheckConstraint(
            "repository_id > 0 AND installation_id > 0 AND run_id > 0 AND run_attempt > 0",
            name=op.f("ck_ci_action_intents_ids_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["orgs.id"], name=op.f("fk_ci_action_intents_org_id_orgs")
        ),
        sa.ForeignKeyConstraint(
            ["principal_id"],
            ["principals.id"],
            name=op.f("fk_ci_action_intents_principal_id_principals"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ci_action_intents")),
        sa.UniqueConstraint("confirmation_id", name="uq_ci_action_intents_confirmation"),
        sa.UniqueConstraint(
            "org_id",
            "action",
            "repository_id",
            "run_id",
            "run_attempt",
            name="uq_ci_action_intents_target",
        ),
    )
    op.create_index(
        op.f("ix_ci_action_intents_org_id"), "ci_action_intents", ["org_id"], unique=False
    )


def downgrade() -> None:
    """Refuse removal of irreversible mutation intent and receipt history."""
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM ci_action_intents)")):
        raise RuntimeError("Cannot downgrade with CI action intent records")

    op.drop_index(op.f("ix_ci_action_intents_org_id"), table_name="ci_action_intents")
    op.drop_table("ci_action_intents")
