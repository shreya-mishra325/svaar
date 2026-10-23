"""Identity tables: organizations, principals, verified bindings and invites."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from svaar.db import Base


class Role(StrEnum):
    """Roles that gate tool access; changes are admin-only for the MVP."""

    OPS = "ops"
    DEV = "dev"
    LEAD = "lead"
    ADMIN = "admin"


ROLE_VALUES = ", ".join(f"'{role.value}'" for role in Role)


class Org(Base):
    """An organization; created only by an operator, never from chat."""

    __tablename__ = "orgs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Principal(Base):
    """A person within exactly one organization."""

    __tablename__ = "principals"
    __table_args__ = (
        UniqueConstraint("org_id", "email", name="uq_principals_org_id_email"),
        CheckConstraint(f"role IN ({ROLE_VALUES})", name="role_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    display_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChannelBinding(Base):
    """A channel address owned by a principal; usable only once verified."""

    __tablename__ = "channel_bindings"
    __table_args__ = (
        UniqueConstraint("channel", "address", name="uq_channel_bindings_channel_address"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    principal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"), index=True)
    channel: Mapped[str] = mapped_column(String(64))
    address: Mapped[str] = mapped_column(String(255))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Invite(Base):
    """A single-use, expiring invite; only the code hash is stored."""

    __tablename__ = "invites"
    __table_args__ = (CheckConstraint(f"role IN ({ROLE_VALUES})", name="role_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_by_principal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PhoneChallenge(Base):
    """Pending number and salted code hash; no binding exists until exact verification."""

    __tablename__ = "phone_challenges"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending', 'verified', 'locked', 'expired', 'canceled')", name="state_valid"
        ),
        CheckConstraint("attempts >= 0 AND attempts <= 3", name="attempts_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id"))
    principal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"), index=True)
    phone_number: Mapped[str] = mapped_column(String(32))
    code_hash: Mapped[str] = mapped_column(String(128))
    code_salt: Mapped[str] = mapped_column(String(32))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(16), default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
