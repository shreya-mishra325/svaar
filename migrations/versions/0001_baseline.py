"""Empty infrastructure baseline; no domain tables.

Revision ID: 0001
Revises: None
"""

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Establish a baseline without creating domain tables."""


def downgrade() -> None:
    """Reverse the empty baseline."""
