"""voice status receipts

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create minimal callback dedupe metadata."""
    op.create_table(
        "voice_webhook_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("voice_call_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["voice_call_id"],
            ["voice_calls.id"],
            name=op.f("fk_voice_webhook_events_voice_call_id_voice_calls"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_voice_webhook_events")),
        sa.UniqueConstraint("execution_id", "status", name="uq_voice_webhook_execution_status"),
    )


def downgrade() -> None:
    """Drop callback metadata."""
    op.drop_table("voice_webhook_events")
