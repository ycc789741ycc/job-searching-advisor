"""Writing events. Always inside the caller's transaction, never outside it."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from kernel.outbox.events import EventName
from kernel.outbox.models import OutboxEvent


async def emit(
    session: AsyncSession,
    name: EventName,
    payload: dict[str, Any],
    *,
    owner_id: uuid.UUID | None = None,
) -> OutboxEvent:
    """Queue a domain event as part of the current unit of work.

    The caller must not commit here; the surrounding ``session.begin()`` block
    commits the change and its event together.
    """
    event = OutboxEvent(name=str(name), owner_id=owner_id, payload=payload)
    session.add(event)
    await session.flush()
    return event
