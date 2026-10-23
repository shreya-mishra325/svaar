"""voice fallback notification dedupe

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this schema change."""
    op.add_column(
        "outbox_messages", sa.Column("notification_key", sa.String(length=128), nullable=True)
    )
    op.create_unique_constraint(
        op.f("uq_outbox_messages_notification_key"), "outbox_messages", ["notification_key"]
    )


def downgrade() -> None:
    """Reverse this schema change."""
    op.drop_constraint(
        op.f("uq_outbox_messages_notification_key"), "outbox_messages", type_="unique"
    )
    op.drop_column("outbox_messages", "notification_key")
