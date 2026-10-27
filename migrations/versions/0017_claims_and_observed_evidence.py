"""claims and observed evidence

Revision ID: 0017
Revises: 0016
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this schema change."""
    op.create_table(
        "claims",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("source_key", sa.String(length=64), nullable=False),
        sa.Column("statement", sa.String(length=4000), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=True),
        sa.Column("run_attempt", sa.Integer(), nullable=True),
        sa.Column("head_sha", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('workflow_succeeded', 'fix_merged')", name=op.f("ck_claims_kind_valid")
        ),
        sa.CheckConstraint(
            "status IN ('confirmed', 'contradicted', 'unverified')",
            name=op.f("ck_claims_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["author_id"], ["principals.id"], name=op.f("fk_claims_author_id_principals")
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"], ["incidents.id"], name=op.f("fk_claims_incident_id_incidents")
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_claims_org_id_orgs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_claims")),
        sa.UniqueConstraint("org_id", "source_key", name="uq_claims_org_source"),
    )
    op.create_index(op.f("ix_claims_incident_id"), "claims", ["incident_id"], unique=False)
    op.create_index(op.f("ix_claims_org_id"), "claims", ["org_id"], unique=False)
    op.create_table(
        "evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("stance", sa.String(length=16), nullable=False),
        sa.Column("rule", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "stance IN ('supports', 'contradicts')", name=op.f("ck_evidence_stance_valid")
        ),
        sa.ForeignKeyConstraint(
            ["claim_id"], ["claims.id"], name=op.f("fk_evidence_claim_id_claims")
        ),
        sa.ForeignKeyConstraint(
            ["event_id"], ["events.id"], name=op.f("fk_evidence_event_id_events")
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_evidence_org_id_orgs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence")),
        sa.UniqueConstraint("claim_id", "event_id", name="uq_evidence_claim_event"),
    )
    op.create_index(op.f("ix_evidence_claim_id"), "evidence", ["claim_id"], unique=False)
    op.create_index(op.f("ix_evidence_org_id"), "evidence", ["org_id"], unique=False)

    op.execute(
        "CREATE FUNCTION svaar_claim_evidence_immutable() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION "
        "'Claim evidence is append-only'; END; $$"
    )
    op.execute(
        "CREATE TRIGGER claim_evidence_append_only BEFORE UPDATE OR DELETE ON evidence "
        "FOR EACH ROW EXECUTE FUNCTION svaar_claim_evidence_immutable()"
    )


def downgrade() -> None:
    """Refuse to silently discard existing claims or their evidence."""
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM claims) THEN "
        "RAISE EXCEPTION 'Archive claims before downgrade'; END IF; END $$"
    )
    op.drop_index(op.f("ix_evidence_org_id"), table_name="evidence")
    op.drop_index(op.f("ix_evidence_claim_id"), table_name="evidence")
    op.drop_table("evidence")
    op.drop_index(op.f("ix_claims_org_id"), table_name="claims")
    op.drop_index(op.f("ix_claims_incident_id"), table_name="claims")
    op.drop_table("claims")

    op.execute("DROP FUNCTION svaar_claim_evidence_immutable()")
