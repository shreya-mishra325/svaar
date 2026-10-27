"""explicit incident ownership

Revision ID: 0016
Revises: 0015
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this schema change."""
    op.add_column("incidents", sa.Column("owner_principal_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_incidents_owner_principal_id_principals"),
        "incidents",
        "principals",
        ["owner_principal_id"],
        ["id"],
    )
    op.add_column("repo_mappings", sa.Column("owner_principal_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_repo_mappings_owner_principal_id_principals"),
        "repo_mappings",
        "principals",
        ["owner_principal_id"],
        ["id"],
    )


def downgrade() -> None:
    """Refuse to discard assigned ownership; otherwise reverse this schema."""
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM repo_mappings "
        "WHERE owner_principal_id IS NOT NULL) OR EXISTS "
        "(SELECT 1 FROM incidents WHERE owner_principal_id IS NOT NULL) THEN "
        "RAISE EXCEPTION 'Reconcile assigned ownership before downgrade'; "
        "END IF; END $$"
    )
    op.drop_constraint(
        op.f("fk_repo_mappings_owner_principal_id_principals"), "repo_mappings", type_="foreignkey"
    )
    op.drop_column("repo_mappings", "owner_principal_id")
    op.drop_constraint(
        op.f("fk_incidents_owner_principal_id_principals"), "incidents", type_="foreignkey"
    )
    op.drop_column("incidents", "owner_principal_id")
