"""claim check calls and answers

Revision ID: 0022
Revises: 0021
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | Sequence[str] | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OPEN_CHECK = (
    "mission = 'claim_check' AND state IN ('pending', 'placing', 'queued', 'active', 'unknown')"
)


def upgrade() -> None:
    """Bind claim_check calls to one claim and allow answer-backed evidence."""
    op.add_column("voice_calls", sa.Column("claim_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_voice_calls_claim_id_claims"), "voice_calls", "claims", ["claim_id"], ["id"]
    )
    op.create_check_constraint(
        op.f("ck_voice_calls_claim_context_valid"),
        "voice_calls",
        "(mission = 'claim_check') = (claim_id IS NOT NULL)",
    )
    op.create_index(
        "uq_voice_calls_open_claim_check",
        "voice_calls",
        ["claim_id"],
        unique=True,
        postgresql_where=sa.text(OPEN_CHECK),
    )
    op.create_table(
        "claim_answers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("answer_hash", sa.String(length=64), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=16), nullable=True),
        sa.Column("decision_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('recorded', 'evidence', 'unverified', 'discarded')",
            name=op.f("ck_claim_answers_state_valid"),
        ),
        sa.CheckConstraint(
            "(state = 'recorded') = (answer_text IS NOT NULL)",
            name=op.f("ck_claim_answers_retention_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["call_id"], ["voice_calls.id"], name=op.f("fk_claim_answers_call_id_voice_calls")
        ),
        sa.ForeignKeyConstraint(
            ["claim_id"], ["claims.id"], name=op.f("fk_claim_answers_claim_id_claims")
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_claim_answers_org_id_orgs")),
        sa.ForeignKeyConstraint(
            ["principal_id"],
            ["principals.id"],
            name=op.f("fk_claim_answers_principal_id_principals"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_claim_answers")),
        sa.UniqueConstraint("call_id", name=op.f("uq_claim_answers_call_id")),
    )
    op.create_index(op.f("ix_claim_answers_claim_id"), "claim_answers", ["claim_id"], unique=False)
    op.alter_column("evidence", "event_id", existing_type=sa.Uuid(), nullable=True)
    op.add_column("evidence", sa.Column("claim_answer_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_evidence_claim_answer_id_claim_answers"),
        "evidence",
        "claim_answers",
        ["claim_answer_id"],
        ["id"],
    )
    op.create_check_constraint(
        op.f("ck_evidence_one_source"),
        "evidence",
        "(event_id IS NULL) <> (claim_answer_id IS NULL)",
    )
    op.create_unique_constraint(
        op.f("uq_evidence_claim_answer"), "evidence", ["claim_id", "claim_answer_id"]
    )


def downgrade() -> None:
    """Refuse to discard call-derived evidence or claim-bound call intents."""
    connection = op.get_bind()
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM claim_answers) "
            "OR EXISTS (SELECT 1 FROM voice_calls WHERE claim_id IS NOT NULL)"
        )
    ):
        raise RuntimeError("Cannot downgrade with claim check records present")
    op.drop_constraint(op.f("uq_evidence_claim_answer"), "evidence", type_="unique")
    op.drop_constraint(op.f("ck_evidence_one_source"), "evidence", type_="check")
    op.drop_constraint(
        op.f("fk_evidence_claim_answer_id_claim_answers"), "evidence", type_="foreignkey"
    )
    op.drop_column("evidence", "claim_answer_id")
    op.alter_column("evidence", "event_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_index(op.f("ix_claim_answers_claim_id"), table_name="claim_answers")
    op.drop_table("claim_answers")
    op.drop_index(
        "uq_voice_calls_open_claim_check",
        table_name="voice_calls",
        postgresql_where=sa.text(OPEN_CHECK),
    )
    op.drop_constraint(op.f("ck_voice_calls_claim_context_valid"), "voice_calls", type_="check")
    op.drop_constraint(op.f("fk_voice_calls_claim_id_claims"), "voice_calls", type_="foreignkey")
    op.drop_column("voice_calls", "claim_id")
