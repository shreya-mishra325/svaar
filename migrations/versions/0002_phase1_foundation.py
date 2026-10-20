"""Identity, actions audit, approvals and decision audit tables.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this schema change."""
    op.create_table(
        "confirmations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("arguments", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("action_hash", sa.String(length=64), nullable=False),
        sa.Column("nonce_hash", sa.String(length=64), nullable=False),
        sa.Column("requested_channel", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_channel", sa.String(length=16), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'confirmed', 'denied', 'expired', 'locked')",
            name=op.f("ck_confirmations_state_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_confirmations")),
    )
    op.create_index(op.f("ix_confirmations_org_id"), "confirmations", ["org_id"], unique=False)
    op.create_index(
        op.f("ix_confirmations_principal_id"), "confirmations", ["principal_id"], unique=False
    )
    op.create_table(
        "decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=True),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("question", sa.String(length=64), nullable=False),
        sa.Column("answer", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("probabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("fallback_reason", sa.String(length=64), nullable=True),
        sa.Column("policy_outcome", sa.String(length=16), nullable=False),
        sa.Column("action_taken", sa.String(length=64), nullable=True),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_decisions")),
    )
    op.create_index(op.f("ix_decisions_incident_id"), "decisions", ["incident_id"], unique=False)
    op.create_index(op.f("ix_decisions_org_id"), "decisions", ["org_id"], unique=False)
    op.create_table(
        "orgs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orgs")),
    )
    op.create_table(
        "tool_executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("tool", sa.String(length=64), nullable=False),
        sa.Column("args_hash", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("risk_tier", sa.Integer(), nullable=True),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("mission", sa.String(length=32), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("confirmation_id", sa.Uuid(), nullable=True),
        sa.Column("execution_key", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed', 'started', 'outcome_unknown', "
            "'confirmation_required', 'invalid_arguments', 'denied', 'unknown_tool')",
            name=op.f("ck_tool_executions_status_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tool_executions")),
        sa.UniqueConstraint("execution_key", name=op.f("uq_tool_executions_execution_key")),
    )
    op.create_index(
        op.f("ix_tool_executions_confirmation_id"),
        "tool_executions",
        ["confirmation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_executions_correlation_id"),
        "tool_executions",
        ["correlation_id"],
        unique=False,
    )
    op.create_index(op.f("ix_tool_executions_org_id"), "tool_executions", ["org_id"], unique=False)
    op.create_index(
        op.f("ix_tool_executions_principal_id"), "tool_executions", ["principal_id"], unique=False
    )
    op.create_table(
        "principals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('ops', 'dev', 'lead', 'admin')", name=op.f("ck_principals_role_valid")
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_principals_org_id_orgs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_principals")),
        sa.UniqueConstraint("org_id", "email", name="uq_principals_org_id_email"),
    )
    op.create_index(op.f("ix_principals_org_id"), "principals", ["org_id"], unique=False)
    op.create_table(
        "channel_bindings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=64), nullable=False),
        sa.Column("address", sa.String(length=255), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["principal_id"],
            ["principals.id"],
            name=op.f("fk_channel_bindings_principal_id_principals"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_channel_bindings")),
        sa.UniqueConstraint("channel", "address", name="uq_channel_bindings_channel_address"),
    )
    op.create_index(
        op.f("ix_channel_bindings_principal_id"), "channel_bindings", ["principal_id"], unique=False
    )
    op.create_table(
        "invites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_by_principal_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('ops', 'dev', 'lead', 'admin')", name=op.f("ck_invites_role_valid")
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_invites_org_id_orgs")),
        sa.ForeignKeyConstraint(
            ["used_by_principal_id"],
            ["principals.id"],
            name=op.f("fk_invites_used_by_principal_id_principals"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invites")),
        sa.UniqueConstraint("code_hash", name=op.f("uq_invites_code_hash")),
    )
    op.create_index(op.f("ix_invites_org_id"), "invites", ["org_id"], unique=False)


def downgrade() -> None:
    """Reverse this schema change."""
    op.drop_index(op.f("ix_invites_org_id"), table_name="invites")
    op.drop_table("invites")
    op.drop_index(op.f("ix_channel_bindings_principal_id"), table_name="channel_bindings")
    op.drop_table("channel_bindings")
    op.drop_index(op.f("ix_principals_org_id"), table_name="principals")
    op.drop_table("principals")
    op.drop_index(op.f("ix_tool_executions_principal_id"), table_name="tool_executions")
    op.drop_index(op.f("ix_tool_executions_org_id"), table_name="tool_executions")
    op.drop_index(op.f("ix_tool_executions_correlation_id"), table_name="tool_executions")
    op.drop_index(op.f("ix_tool_executions_confirmation_id"), table_name="tool_executions")
    op.drop_table("tool_executions")
    op.drop_table("orgs")
    op.drop_index(op.f("ix_decisions_org_id"), table_name="decisions")
    op.drop_index(op.f("ix_decisions_incident_id"), table_name="decisions")
    op.drop_table("decisions")
    op.drop_index(op.f("ix_confirmations_principal_id"), table_name="confirmations")
    op.drop_index(op.f("ix_confirmations_org_id"), table_name="confirmations")
    op.drop_table("confirmations")
