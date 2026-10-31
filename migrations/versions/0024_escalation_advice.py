"""escalation advice

Revision ID: 0024
Revises: 0023
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Record when alert-time advice was asked, so it is asked at most once."""
    op.add_column(
        "escalation_jobs", sa.Column("advised_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Advice timestamps are audit metadata only; decisions keep the full record."""
    op.drop_column("escalation_jobs", "advised_at")
