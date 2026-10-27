"""Explicit GitHub repository scope and durable authenticated delivery receipts."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from svaar.db import Base


class RepoMapping(Base):
    """A repository belongs to one organization through one approved installation."""

    __tablename__ = "repo_mappings"
    __table_args__ = (
        CheckConstraint("repository_id > 0 AND installation_id > 0", name="ids_valid"),
    )

    repository_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    installation_id: Mapped[int] = mapped_column(BigInteger)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id"), index=True)
    owner_principal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))


class WebhookDelivery(Base):
    """Hash/receipt metadata only; no raw webhook payload or sender personal data."""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (CheckConstraint("state IN ('accepted', 'ignored')", name="state_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64))
    payload_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(String(64))
    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orgs.id"))
    event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("events.id"))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
