"""Incident aggregate and incident-event membership; observed events stay immutable.

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this schema change."""
    op.create_table(
        "incidents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.BigInteger(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("workflow_id", sa.BigInteger(), nullable=True),
        sa.Column("workflow_name", sa.String(length=200), nullable=True),
        sa.Column("head_branch", sa.String(length=255), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('open', 'acknowledged', 'resolved')", name=op.f("ck_incidents_state_valid")
        ),
        sa.CheckConstraint("failure_count > 0", name=op.f("ck_incidents_failure_count_positive")),
        sa.ForeignKeyConstraint(
            ["acknowledged_by"],
            ["principals.id"],
            name=op.f("fk_incidents_acknowledged_by_principals"),
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_incidents_org_id_orgs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incidents")),
    )
    op.create_index(op.f("ix_incidents_org_id"), "incidents", ["org_id"], unique=False)
    op.create_index(
        "uq_incidents_active_fingerprint",
        "incidents",
        ["org_id", "fingerprint"],
        unique=True,
        postgresql_where=sa.text("state IN ('open', 'acknowledged')"),
    )
    op.create_table(
        "incident_events",
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column(
            "linked_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["event_id"], ["events.id"], name=op.f("fk_incident_events_event_id_events")
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"], ["incidents.id"], name=op.f("fk_incident_events_incident_id_incidents")
        ),
        sa.PrimaryKeyConstraint("incident_id", "event_id", name=op.f("pk_incident_events")),
        sa.UniqueConstraint("event_id", name=op.f("uq_incident_events_event_id")),
    )


def downgrade() -> None:
    """Reverse this schema change."""
    op.drop_table("incident_events")
    op.drop_index(
        "uq_incidents_active_fingerprint",
        table_name="incidents",
        postgresql_where=sa.text("state IN ('open', 'acknowledged')"),
    )
    op.drop_index(op.f("ix_incidents_org_id"), table_name="incidents")
    op.drop_table("incidents")
