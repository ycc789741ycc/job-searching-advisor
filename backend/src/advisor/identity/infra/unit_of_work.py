"""Identity's unit of work over SQL.

``for_owner`` opens ``Database.for_user`` and ``unauthenticated`` opens
``Database.shared`` — exactly the sessions the use cases opened themselves —
so row-level security applies as before. Events recorded in the owner scope go
to the outbox in the same transaction, just before it commits.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, assert_never

from sqlalchemy.ext.asyncio import AsyncSession

from advisor.identity.domain import (
    IdentityEvent,
    ProviderCredentialFailed,
    UsageBudgetExceeded,
)
from advisor.identity.infra.repositories import (
    SqlAlchemyAccountRepository,
    SqlAlchemyAiUsageBudgetRepository,
    SqlAlchemyAiUsageEntryRepository,
    SqlAlchemyFederatedIdentityRepository,
    SqlAlchemyPasswordCredentialRepository,
    SqlAlchemyProviderCredentialRepository,
    SqlAlchemyRefreshTokenRepository,
)
from kernel.db import Database
from kernel.outbox import EventName, emit


class SqlAlchemyAuthentication:
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID | None = None) -> None:
        self.accounts = SqlAlchemyAccountRepository(session)
        self.passwords = SqlAlchemyPasswordCredentialRepository(session, owner_id=owner_id)
        self.federated = SqlAlchemyFederatedIdentityRepository(session, owner_id=owner_id)
        self.refresh_tokens = SqlAlchemyRefreshTokenRepository(session, owner_id=owner_id)


class SqlAlchemyOwnerIdentity(SqlAlchemyAuthentication):
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        super().__init__(session, owner_id)
        self.credentials = SqlAlchemyProviderCredentialRepository(session, owner_id=owner_id)
        self.budgets = SqlAlchemyAiUsageBudgetRepository(session, owner_id=owner_id)
        self.usage = SqlAlchemyAiUsageEntryRepository(session, owner_id=owner_id)
        self.pending: list[IdentityEvent] = []

    def record(self, event: IdentityEvent) -> None:
        self.pending.append(event)


class SqlAlchemyIdentityUnitOfWork:
    def __init__(self, database: Database) -> None:
        self._db = database

    @asynccontextmanager
    async def for_owner(self, owner_id: uuid.UUID) -> AsyncIterator[SqlAlchemyOwnerIdentity]:
        async with self._db.for_user(owner_id) as session:
            scope = SqlAlchemyOwnerIdentity(session, owner_id)
            yield scope
            for event in scope.pending:
                name, payload, owner = _outbox_entry(event)
                await emit(session, name, payload, owner_id=owner)

    @asynccontextmanager
    async def unauthenticated(self) -> AsyncIterator[SqlAlchemyAuthentication]:
        async with self._db.shared() as session:
            yield SqlAlchemyAuthentication(session)


def _outbox_entry(event: IdentityEvent) -> tuple[EventName, dict[str, Any], uuid.UUID]:
    """The outbox name, payload and routing owner for each identity event.

    These payloads are a contract with the dispatcher and must not drift.
    """
    match event:
        case ProviderCredentialFailed():
            return EventName.PROVIDER_CREDENTIAL_FAILED, {"reason": event.reason}, event.owner_id
        case UsageBudgetExceeded():
            return (
                EventName.USAGE_BUDGET_EXCEEDED,
                {
                    "cap_usd": str(event.cap_usd),
                    "spent_usd": str(event.spent_usd),
                    "estimated_usd": str(event.estimated_usd),
                },
                event.owner_id,
            )
        case _:
            assert_never(event)
