"""Durable gateway event cursor and process heartbeat

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this schema change."""
    op.create_table(
        "gateway_cursors",
        sa.Column("stream_key", sa.String(length=64), nullable=False),
        sa.Column("last_seq", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "heartbeat_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('processing', 'ready', 'blocked_identity', 'error', 'stopped')",
            name=op.f("ck_gateway_cursors_state_valid"),
        ),
        sa.CheckConstraint("last_seq >= 0", name=op.f("ck_gateway_cursors_cursor_valid")),
        sa.PrimaryKeyConstraint("stream_key", name=op.f("pk_gateway_cursors")),
    )


def downgrade() -> None:
    """Reverse this schema change."""
    op.drop_table("gateway_cursors")
