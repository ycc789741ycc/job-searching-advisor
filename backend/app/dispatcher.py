"""The outbox dispatcher.

Turns committed domain events into queued jobs. This is also where a market
event becomes user work: the crawler emits ``PostingsChanged`` about a company
or a market and knows nothing about users, so the fan-out happens here, where
user data is legitimately readable (docs/technical_boundaries.md section 2).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, text

from app.container import Container
from app.queue import enqueue
from kernel.db.base import utcnow
from kernel.logging import get_logger
from kernel.outbox import EventName, OutboxEvent

log = get_logger(__name__)

BATCH_SIZE = 100


async def dispatch_pending(deps: Container, *, limit: int = BATCH_SIZE) -> int:
    """Claim undispatched events and turn them into jobs.

    ``FOR UPDATE SKIP LOCKED`` means several dispatchers can run without
    handling the same row twice.
    """
    async with deps.database.shared() as session:
        rows = await session.execute(
            select(OutboxEvent)
            .where(OutboxEvent.dispatched_at.is_(None))
            .order_by(OutboxEvent.occurred_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        events = list(rows.scalars())
        for event in events:
            try:
                await _handle(deps, event)
            except Exception as exc:
                event.attempts += 1
                event.last_error = f"{exc.__class__.__name__}: {exc}"
                log.error(
                    "outbox.dispatch_failed",
                    event_name=event.name,
                    event_id=str(event.id),
                    attempts=event.attempts,
                )
                continue
            event.dispatched_at = utcnow()
    return len(events)


async def _handle(deps: Container, event: OutboxEvent) -> None:
    name = event.name
    owner_id = event.owner_id

    if name == EventName.SOURCE_SYNCED:
        # Deliberately does not start an analysis: the user asks for that
        # explicitly, and every sync would otherwise spend their money.
        return

    if name in (EventName.ASSESSMENT_COMPLETED, EventName.DIMENSIONS_CHANGED) and owner_id:
        await enqueue("assessment.compute_fits", owner_id=str(owner_id))
        return

    if name == EventName.ROLE_REQUIREMENTS_CHANGED and owner_id:
        await enqueue("assessment.compute_fits", owner_id=str(owner_id))
        return

    if name == EventName.SUBSCRIPTION_ADDED or name == EventName.MARKET_SELECTED:
        await enqueue("market.materialize_crawl_sources")
        return

    if name == EventName.POSTINGS_CHANGED:
        for affected in await _users_affected_by(deps, event.payload):
            await enqueue("rolemap.recluster", owner_id=str(affected))
        return


async def _users_affected_by(deps: Container, payload: dict[str, Any]) -> list[uuid.UUID]:
    """Resolve a market change to the users who care about it.

    The crawler cannot do this — it has no grant on any user schema — which is
    the whole reason the fan-out lives here.
    """
    company_id = payload.get("company_id")
    market = payload.get("market")
    affected: set[uuid.UUID] = set()

    async with deps.database.fanout() as session:
        if company_id:
            rows = await session.execute(
                text(
                    "SELECT DISTINCT owner_id FROM market_user.company_subscription "
                    "WHERE company_id = :company_id"
                ),
                {"company_id": company_id},
            )
            affected.update(rows.scalars())
        if market:
            rows = await session.execute(
                text(
                    "SELECT DISTINCT owner_id FROM market_user.market_preference "
                    "WHERE market = :market"
                ),
                {"market": market},
            )
            affected.update(rows.scalars())
    return sorted(affected)
