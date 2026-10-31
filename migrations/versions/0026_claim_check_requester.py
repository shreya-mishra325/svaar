"""claim check requester

Revision ID: 0026
Revises: 0025
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | Sequence[str] | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Record who requested a call, so a failed claim check is reported to them."""
    op.add_column("voice_calls", sa.Column("requested_by", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_voice_calls_requested_by_principals"),
        "voice_calls",
        "principals",
        ["requested_by"],
        ["id"],
    )


def downgrade() -> None:
    """The requester is notification routing only; call receipts remain intact."""
    op.drop_constraint(
        op.f("fk_voice_calls_requested_by_principals"), "voice_calls", type_="foreignkey"
    )
    op.drop_column("voice_calls", "requested_by")
