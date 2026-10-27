"""standing constraints and tracked drafts

Revision ID: 0019
Revises: 0018
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this schema change."""
    op.create_table(
        "constraints",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("owner_agent", sa.String(length=16), nullable=False),
        sa.Column("rule", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "owner_agent IN ('release', 'staffing', 'capacity')",
            name=op.f("ck_constraints_agent_valid"),
        ),
        sa.CheckConstraint("revision > 0", name=op.f("ck_constraints_revision_positive")),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_constraints_org_id_orgs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_constraints")),
        sa.UniqueConstraint("org_id", "owner_agent", name="uq_constraints_org_agent"),
    )
    op.create_index(op.f("ix_constraints_org_id"), "constraints", ["org_id"], unique=False)
    op.create_table(
        "exception_drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("negotiation_id", sa.Uuid(), nullable=False),
        sa.Column("constraints_revision", sa.Integer(), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(state = 'draft' AND approved_by IS NULL AND approved_at IS NULL) "
            "OR (state = 'approved' AND approved_by IS NOT NULL AND approved_at IS NOT NULL)",
            name=op.f("ck_exception_drafts_approval_valid"),
        ),
        sa.CheckConstraint(
            "state IN ('draft', 'approved')", name=op.f("ck_exception_drafts_state_valid")
        ),
        sa.CheckConstraint(
            "constraints_revision > 0", name=op.f("ck_exception_drafts_revision_positive")
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["principals.id"],
            name=op.f("fk_exception_drafts_approved_by_principals"),
        ),
        sa.ForeignKeyConstraint(
            ["negotiation_id"],
            ["negotiations.id"],
            name=op.f("fk_exception_drafts_negotiation_id_negotiations"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["orgs.id"], name=op.f("fk_exception_drafts_org_id_orgs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exception_drafts")),
        sa.UniqueConstraint("negotiation_id", name="uq_exception_drafts_negotiation"),
    )
    op.create_index(
        op.f("ix_exception_drafts_org_id"), "exception_drafts", ["org_id"], unique=False
    )
    op.add_column("negotiations", sa.Column("constraints_revision", sa.Integer(), nullable=True))
    op.add_column("replay_runs", sa.Column("negotiation_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_replay_runs_negotiation_id_negotiations"),
        "replay_runs",
        "negotiations",
        ["negotiation_id"],
        ["id"],
    )

    op.execute("""
        CREATE FUNCTION guard_exception_draft() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Exception drafts are retained';
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id
                OR NEW.org_id IS DISTINCT FROM OLD.org_id
                OR NEW.negotiation_id IS DISTINCT FROM OLD.negotiation_id
                OR NEW.constraints_revision IS DISTINCT FROM OLD.constraints_revision
                OR NEW.content IS DISTINCT FROM OLD.content
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
                OR OLD.state = 'approved' THEN
                RAISE EXCEPTION 'Exception draft content and completed approvals are immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER exception_drafts_immutable
        BEFORE UPDATE OR DELETE ON exception_drafts
        FOR EACH ROW EXECUTE FUNCTION guard_exception_draft()
    """)


def downgrade() -> None:
    """Refuse removal of standing rules and linked approval provenance."""
    connection = op.get_bind()
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM constraints) "
            "OR EXISTS (SELECT 1 FROM exception_drafts) "
            "OR EXISTS (SELECT 1 FROM negotiations WHERE constraints_revision IS NOT NULL) "
            "OR EXISTS (SELECT 1 FROM replay_runs WHERE negotiation_id IS NOT NULL)"
        )
    ):
        raise RuntimeError("Cannot downgrade with standing-policy or draft records")
    op.execute("DROP TRIGGER exception_drafts_immutable ON exception_drafts")
    op.execute("DROP FUNCTION guard_exception_draft()")

    op.drop_constraint(
        op.f("fk_replay_runs_negotiation_id_negotiations"), "replay_runs", type_="foreignkey"
    )
    op.drop_column("replay_runs", "negotiation_id")
    op.drop_column("negotiations", "constraints_revision")
    op.drop_index(op.f("ix_exception_drafts_org_id"), table_name="exception_drafts")
    op.drop_table("exception_drafts")
    op.drop_index(op.f("ix_constraints_org_id"), table_name="constraints")
    op.drop_table("constraints")
