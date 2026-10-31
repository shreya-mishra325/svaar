"""voice placement time

Revision ID: 0025
Revises: 0024
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | Sequence[str] | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Record when a call was claimed for placement, for per-recipient limits."""
    op.add_column("voice_calls", sa.Column("placed_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "UPDATE voice_calls SET placed_at = created_at "
        "WHERE state <> 'pending' AND call_ref_hash IS NOT NULL"
    )


def downgrade() -> None:
    """Placement times are limit metadata; call receipts remain intact."""
    op.drop_column("voice_calls", "placed_at")
