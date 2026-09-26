"""The market's unit of work over SQL: one transaction per scope.

Each scope opens exactly the session the use case used to open itself —
``for_user``, ``shared`` or ``fanout`` from ``kernel.db`` — so row-level
security and the fan-out policy apply as before. Events recorded in a scope go
to the outbox in the same transaction, just before it commits.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, assert_never

from sqlalchemy.ext.asyncio import AsyncSession

from advisor.market.domain import (
    MarketEvent,
    MarketSelected,
    PostingsChanged,
    SubscriptionAdded,
)
from advisor.market.infra.repositories import (
    SqlCompanyRepository,
    SqlCrawlSourceRepository,
    SqlJobPostingRepository,
    SqlManualRefreshRepository,
    SqlMarketPreferenceRepository,
    SqlPrivatePostingRepository,
    SqlSubscriptionRepository,
    SqlWatchers,
)
from kernel.db import Database
from kernel.outbox import EventName, emit


class _Events:
    def __init__(self) -> None:
        self.pending: list[MarketEvent] = []

    def record(self, event: MarketEvent) -> None:
        self.pending.append(event)

    async def flush(self, session: AsyncSession) -> None:
        for event in self.pending:
            name, payload, owner_id = _outbox_entry(event)
            await emit(session, name, payload, owner_id=owner_id)
        self.pending.clear()


class SqlSharedMarket(_Events):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self.companies = SqlCompanyRepository(session)
        self.sources = SqlCrawlSourceRepository(session)
        self.postings = SqlJobPostingRepository(session)


class SqlOwnerMarket(_Events):
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        super().__init__()
        self.subscriptions = SqlSubscriptionRepository(session, owner_id)
        self.markets = SqlMarketPreferenceRepository(session, owner_id)
        self.private_postings = SqlPrivatePostingRepository(session, owner_id)
        self.refreshes = SqlManualRefreshRepository(session, owner_id)


class SqlMarketUnitOfWork:
    def __init__(self, database: Database) -> None:
        self._db = database

    @asynccontextmanager
    async def for_owner(self, owner_id: uuid.UUID) -> AsyncIterator[SqlOwnerMarket]:
        async with self._db.for_user(owner_id) as session:
            scope = SqlOwnerMarket(session, owner_id)
            yield scope
            await scope.flush(session)

    @asynccontextmanager
    async def shared(self) -> AsyncIterator[SqlSharedMarket]:
        async with self._db.shared() as session:
            scope = SqlSharedMarket(session)
            yield scope
            await scope.flush(session)

    @asynccontextmanager
    async def fanout(self) -> AsyncIterator[SqlWatchers]:
        async with self._db.fanout() as session:
            yield SqlWatchers(session)


def _outbox_entry(event: MarketEvent) -> tuple[EventName, dict[str, Any], uuid.UUID | None]:
    """The outbox name, payload and routing owner for each market event.

    These payloads are a contract with the dispatcher and must not drift.
    """
    match event:
        case SubscriptionAdded():
            return (
                EventName.SUBSCRIPTION_ADDED,
                {"company_id": str(event.company_id), "company_name": event.company_name},
                event.owner_id,
            )
        case MarketSelected():
            return EventName.MARKET_SELECTED, {"market": event.market}, event.owner_id
        case PostingsChanged():
            return (
                EventName.POSTINGS_CHANGED,
                {
                    "company_id": str(event.company_id) if event.company_id else None,
                    "market": event.market,
                    "seen": event.seen,
                    "expired": event.expired,
                },
                None,
            )
        case _:
            assert_never(event)
