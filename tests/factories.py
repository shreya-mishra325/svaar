"""Small builders for database tests; they bypass invites only to set up fixtures."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from svaar.identity.models import ChannelBinding, Org, Principal, Role


def make_org(session: Session, name: str = "Example Org") -> Org:
    """Create and flush an organization."""
    org = Org(name=name)
    session.add(org)
    session.flush()
    return org


def make_principal(
    session: Session,
    org: Org,
    role: Role = Role.DEV,
    *,
    bindings: tuple[tuple[str, str], ...] = (),
    verified: bool = True,
) -> Principal:
    """Create a principal with optional (channel, address) bindings."""
    principal = Principal(org_id=org.id, role=role.value, display_name="Test Person")
    session.add(principal)
    session.flush()
    for channel, address in bindings:
        session.add(
            ChannelBinding(
                principal_id=principal.id,
                channel=channel,
                address=address,
                verified_at=datetime.now(UTC) if verified else None,
            )
        )
    session.flush()
    return principal
