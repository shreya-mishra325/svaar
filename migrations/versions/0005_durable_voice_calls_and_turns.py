"""durable voice calls and turns

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this schema change."""
    op.create_table(
        "voice_calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("phone_binding_id", sa.Uuid(), nullable=False),
        sa.Column("mission", sa.String(length=24), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "mission IN ('escalation', 'claim_check', 'confirmation')",
            name=op.f("ck_voice_calls_mission_valid"),
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'active', 'closed')", name=op.f("ck_voice_calls_state_valid")
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_voice_calls_org_id_orgs")),
        sa.ForeignKeyConstraint(
            ["phone_binding_id"],
            ["channel_bindings.id"],
            name=op.f("fk_voice_calls_phone_binding_id_channel_bindings"),
        ),
        sa.ForeignKeyConstraint(
            ["principal_id"], ["principals.id"], name=op.f("fk_voice_calls_principal_id_principals")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_voice_calls")),
    )
    op.create_table(
        "voice_turns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("voice_call_id", sa.Uuid(), nullable=False),
        sa.Column("turn_index", sa.Integer(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("user_text", sa.Text(), nullable=True),
        sa.Column("reply", sa.Text(), nullable=True),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('processing', 'processed', 'unknown')",
            name=op.f("ck_voice_turns_state_valid"),
        ),
        sa.CheckConstraint("turn_index >= 0", name=op.f("ck_voice_turns_index_valid")),
        sa.ForeignKeyConstraint(
            ["voice_call_id"],
            ["voice_calls.id"],
            name=op.f("fk_voice_turns_voice_call_id_voice_calls"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_voice_turns")),
        sa.UniqueConstraint("voice_call_id", "turn_index", name="uq_voice_turns_call_index"),
    )
    op.create_index(
        op.f("ix_voice_turns_voice_call_id"), "voice_turns", ["voice_call_id"], unique=False
    )


def downgrade() -> None:
    """Reverse this schema change."""
    op.drop_index(op.f("ix_voice_turns_voice_call_id"), table_name="voice_turns")
    op.drop_table("voice_turns")
    op.drop_table("voice_calls")
