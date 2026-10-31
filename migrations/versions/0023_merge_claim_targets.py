"""merge claim targets

Revision ID: 0023
Revises: 0022
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | Sequence[str] | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Let a fix_merged claim name the pull request whose merge would support it."""
    op.add_column("claims", sa.Column("pull_number", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f("ck_claims_pull_number_target_valid"),
        "claims",
        "pull_number IS NULL OR kind = 'fix_merged'",
    )


def downgrade() -> None:
    """Refuse to drop recorded merge targets."""
    connection = op.get_bind()
    if connection.scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM claims WHERE pull_number IS NOT NULL)")
    ):
        raise RuntimeError("Cannot downgrade with merge claim targets present")
    op.drop_constraint(op.f("ck_claims_pull_number_target_valid"), "claims", type_="check")
    op.drop_column("claims", "pull_number")
