"""phone challenge outbox delivery

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this schema change."""
    op.add_column("outbox_messages", sa.Column("phone_challenge_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_outbox_messages_phone_challenge_id_phone_challenges"),
        "outbox_messages",
        "phone_challenges",
        ["phone_challenge_id"],
        ["id"],
    )


def downgrade() -> None:
    """Refuse to discard delivery guards while secret deliveries need reconciliation."""
    unresolved = op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM outbox_messages WHERE phone_challenge_id IS NOT NULL "
            "AND state IN ('pending', 'sending', 'queued', 'unknown')"
        )
    )
    if unresolved:
        raise RuntimeError("Reconcile phone challenge deliveries before downgrade")

    op.drop_constraint(
        op.f("fk_outbox_messages_phone_challenge_id_phone_challenges"),
        "outbox_messages",
        type_="foreignkey",
    )
    op.drop_column("outbox_messages", "phone_challenge_id")
