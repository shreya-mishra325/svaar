"""durable voice placement outcomes

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this schema change."""
    op.drop_constraint(op.f("ck_voice_calls_state_valid"), "voice_calls", type_="check")
    op.create_check_constraint(
        "state_valid",
        "voice_calls",
        "state IN ('pending', 'placing', 'queued', 'active', 'closed', 'failed', 'unknown')",
    )

    op.add_column("voice_calls", sa.Column("execution_id", sa.Uuid(), nullable=True))
    op.add_column("voice_calls", sa.Column("provider_agent_id", sa.Uuid(), nullable=True))
    op.add_column("voice_calls", sa.Column("provider_status", sa.String(length=32), nullable=True))
    op.add_column("voice_calls", sa.Column("call_ref_hash", sa.String(length=64), nullable=True))
    op.add_column("voice_calls", sa.Column("error_code", sa.String(length=64), nullable=True))
    op.create_unique_constraint(
        op.f("uq_voice_calls_call_ref_hash"), "voice_calls", ["call_ref_hash"]
    )
    op.create_unique_constraint(
        op.f("uq_voice_calls_execution_id"), "voice_calls", ["execution_id"]
    )


def downgrade() -> None:
    """Reverse only after new placement states have been reconciled by an operator.

    Existing new states intentionally cause a constraint failure rather than
    being reset to pending, which could place duplicate calls.
    """
    op.drop_constraint(op.f("ck_voice_calls_state_valid"), "voice_calls", type_="check")
    op.create_check_constraint(
        "state_valid", "voice_calls", "state IN ('pending', 'active', 'closed')"
    )

    op.drop_constraint(op.f("uq_voice_calls_execution_id"), "voice_calls", type_="unique")
    op.drop_constraint(op.f("uq_voice_calls_call_ref_hash"), "voice_calls", type_="unique")
    op.drop_column("voice_calls", "error_code")
    op.drop_column("voice_calls", "call_ref_hash")
    op.drop_column("voice_calls", "provider_status")
    op.drop_column("voice_calls", "provider_agent_id")
    op.drop_column("voice_calls", "execution_id")
