"""Join main incident/resolution/replay migrations and voice receipts.

Revision ID: 0014
Revises: 0013, 0011_voice
"""

revision = "0014"
down_revision = ("0013", "0011_voice")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Both schema branches are already applied."""


def downgrade() -> None:
    """Return to the two existing branch heads without dropping data."""
