"""guarded escalation preparation

Revision ID: 0018
Revises: 0017
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this schema change."""
    op.create_table(
        "escalation_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=True),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(state = 'prepared' AND call_id IS NOT NULL AND prepared_at IS NOT NULL) "
            "OR (state <> 'prepared' AND call_id IS NULL AND prepared_at IS NULL)",
            name=op.f("ck_escalation_jobs_prepared_valid"),
        ),
        sa.CheckConstraint(
            "state IN ('waiting', 'deferred', 'prepared', 'canceled')",
            name=op.f("ck_escalation_jobs_state_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["call_id"], ["voice_calls.id"], name=op.f("fk_escalation_jobs_call_id_voice_calls")
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"], ["incidents.id"], name=op.f("fk_escalation_jobs_incident_id_incidents")
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["orgs.id"], name=op.f("fk_escalation_jobs_org_id_orgs")
        ),
        sa.ForeignKeyConstraint(
            ["principal_id"],
            ["principals.id"],
            name=op.f("fk_escalation_jobs_principal_id_principals"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_escalation_jobs")),
        sa.UniqueConstraint("call_id", name=op.f("uq_escalation_jobs_call_id")),
        sa.UniqueConstraint("incident_id", name=op.f("uq_escalation_jobs_incident_id")),
    )
    op.create_index(
        "ix_escalation_jobs_recipient",
        "escalation_jobs",
        ["org_id", "principal_id", "prepared_at"],
        unique=False,
    )
    op.add_column("voice_calls", sa.Column("incident_id", sa.Uuid(), nullable=True))
    op.create_index(
        "uq_voice_calls_escalation_incident",
        "voice_calls",
        ["incident_id"],
        unique=True,
        postgresql_where=sa.text("mission = 'escalation' AND incident_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Refuse removal of durable escalation safety records."""
    connection = op.get_bind()
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM escalation_jobs) "
            "OR EXISTS (SELECT 1 FROM voice_calls WHERE incident_id IS NOT NULL)"
        )
    ):
        raise RuntimeError("Cannot downgrade with escalation records present")
    op.drop_index(
        "uq_voice_calls_escalation_incident",
        table_name="voice_calls",
        postgresql_where=sa.text("mission = 'escalation' AND incident_id IS NOT NULL"),
    )
    op.drop_column("voice_calls", "incident_id")
    op.drop_index("ix_escalation_jobs_recipient", table_name="escalation_jobs")
    op.drop_table("escalation_jobs")
