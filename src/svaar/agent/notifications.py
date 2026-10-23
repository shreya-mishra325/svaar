"""Private follow-ups through the existing durable outbox, never direct provider sends."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from svaar.agent.models import Conversation, InboundRecord, OutboxMessage
from svaar.identity.models import ChannelBinding
from svaar.identity.service import resolve_principal

FOLLOW_UP = (
    "I couldn't complete a request during your call. Please continue in this private chat. "
    "If an action may have started, ask an operator to review its outcome before retrying."
)


def _existing_notification(
    session: Session,
    key: str,
    org_id: uuid.UUID,
    principal_id: uuid.UUID,
) -> bool | None:
    row = session.execute(
        select(OutboxMessage.state, Conversation.org_id, Conversation.principal_id)
        .join(InboundRecord, InboundRecord.id == OutboxMessage.inbound_id)
        .join(Conversation, Conversation.id == InboundRecord.conversation_id)
        .where(OutboxMessage.notification_key == key)
    ).one_or_none()
    if row is None:
        return None
    return (
        row.org_id == org_id
        and row.principal_id == principal_id
        and row.state in {"pending", "sending", "queued", "sent"}
    )


def enqueue_voice_fallback(
    session: Session,
    org_id: uuid.UUID,
    principal_id: uuid.UUID,
    call_id: uuid.UUID,
    turn_index: int,
) -> bool:
    """Queue once to a single verified private conversation; ambiguous routes refuse.

    The principal and organization come from the resolved call, never model text.
    Locking the processed inbound anchor reserves the next outbox ordinal without
    fabricating inbound messages or changing the delivery adapter.
    """
    key = f"voice-fallback:{call_id}:{turn_index}"
    existing = _existing_notification(session, key, org_id, principal_id)
    if existing is not None:
        return existing
    routes = list(
        session.scalars(
            select(Conversation.id)
            .join(InboundRecord, InboundRecord.conversation_id == Conversation.id)
            .join(
                ChannelBinding,
                (ChannelBinding.channel == InboundRecord.channel)
                & (ChannelBinding.address == InboundRecord.sender_address)
                & (ChannelBinding.principal_id == principal_id),
            )
            .where(
                Conversation.org_id == org_id,
                Conversation.principal_id == principal_id,
                ChannelBinding.verified_at.is_not(None),
                InboundRecord.state == "processed",
            )
            .distinct()
            .limit(2)
        )
    )
    if len(routes) != 1:
        return False
    anchor = session.scalar(
        select(InboundRecord)
        .where(
            InboundRecord.conversation_id == routes[0],
            InboundRecord.state == "processed",
        )
        .order_by(InboundRecord.created_at.desc(), InboundRecord.id.desc())
        .with_for_update()
        .limit(1)
    )
    existing = _existing_notification(session, key, org_id, principal_id)
    if existing is not None:
        return existing
    principal = resolve_principal(session, anchor.channel, anchor.sender_address)
    if principal is None or principal.id != principal_id or principal.org_id != org_id:
        return False
    ordinal = (
        session.scalar(
            select(func.coalesce(func.max(OutboxMessage.ordinal), -1)).where(
                OutboxMessage.inbound_id == anchor.id
            )
        )
        + 1
    )
    session.add(
        OutboxMessage(
            inbound_id=anchor.id,
            ordinal=ordinal,
            body=FOLLOW_UP,
            notification_key=key,
        )
    )
    session.flush()
    return True
