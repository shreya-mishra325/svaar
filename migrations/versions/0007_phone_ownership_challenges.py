"""phone ownership challenges

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this schema change."""
    op.create_table(
        "phone_challenges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("phone_number", sa.String(length=32), nullable=False),
        sa.Column("code_hash", sa.String(length=128), nullable=False),
        sa.Column("code_salt", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'verified', 'locked', 'expired', 'canceled')",
            name=op.f("ck_phone_challenges_state_valid"),
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND attempts <= 3", name=op.f("ck_phone_challenges_attempts_valid")
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["orgs.id"], name=op.f("fk_phone_challenges_org_id_orgs")
        ),
        sa.ForeignKeyConstraint(
            ["principal_id"],
            ["principals.id"],
            name=op.f("fk_phone_challenges_principal_id_principals"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_phone_challenges")),
    )
    op.create_index(
        op.f("ix_phone_challenges_principal_id"), "phone_challenges", ["principal_id"], unique=False
    )
    op.add_column("voice_calls", sa.Column("phone_challenge_id", sa.Uuid(), nullable=True))
    op.alter_column("voice_calls", "phone_binding_id", existing_type=sa.UUID(), nullable=True)
    op.create_unique_constraint(
        op.f("uq_voice_calls_phone_challenge_id"), "voice_calls", ["phone_challenge_id"]
    )
    op.create_foreign_key(
        op.f("fk_voice_calls_phone_challenge_id_phone_challenges"),
        "voice_calls",
        "phone_challenges",
        ["phone_challenge_id"],
        ["id"],
    )

    op.drop_constraint(op.f("ck_voice_calls_mission_valid"), "voice_calls", type_="check")
    op.create_check_constraint(
        "mission_valid",
        "voice_calls",
        "mission IN ('escalation', 'claim_check', 'confirmation', 'phone_verify')",
    )
    op.create_check_constraint(
        "phone_context_valid",
        "voice_calls",
        "(mission = 'phone_verify' AND phone_challenge_id IS NOT NULL "
        "AND phone_binding_id IS NULL) OR "
        "(mission <> 'phone_verify' AND phone_challenge_id IS NULL "
        "AND phone_binding_id IS NOT NULL)",
    )


def downgrade() -> None:
    """Reverse only after verification calls have been reviewed and removed."""
    op.drop_constraint(op.f("ck_voice_calls_phone_context_valid"), "voice_calls", type_="check")
    op.drop_constraint(op.f("ck_voice_calls_mission_valid"), "voice_calls", type_="check")
    op.create_check_constraint(
        "mission_valid", "voice_calls", "mission IN ('escalation', 'claim_check', 'confirmation')"
    )

    op.drop_constraint(
        op.f("fk_voice_calls_phone_challenge_id_phone_challenges"),
        "voice_calls",
        type_="foreignkey",
    )
    op.drop_constraint(op.f("uq_voice_calls_phone_challenge_id"), "voice_calls", type_="unique")
    op.alter_column("voice_calls", "phone_binding_id", existing_type=sa.UUID(), nullable=False)
    op.drop_column("voice_calls", "phone_challenge_id")
    op.drop_index(op.f("ix_phone_challenges_principal_id"), table_name="phone_challenges")
    op.drop_table("phone_challenges")
