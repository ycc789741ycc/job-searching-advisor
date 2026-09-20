"""Repositories for the identity schema. No business rules live here."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kernel.db.base import utcnow
from modules.identity.infra.models import (
    Account,
    AiUsageBudget,
    AiUsageLedger,
    ProviderCredential,
)


class AccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def by_auth_subject(self, subject: str) -> Account | None:
        result = await self._session.execute(select(Account).where(Account.auth_subject == subject))
        return result.scalar_one_or_none()

    async def by_id(self, account_id: uuid.UUID) -> Account | None:
        return await self._session.get(Account, account_id)

    def add(self, account: Account) -> None:
        self._session.add(account)

    async def pause_background_jobs(self, account_id: uuid.UUID, reason: str) -> None:
        account = await self._session.get(Account, account_id)
        if account is not None:
            account.background_jobs_paused_at = utcnow()
            account.paused_reason = reason

    async def resume_background_jobs(self, account_id: uuid.UUID) -> None:
        account = await self._session.get(Account, account_id)
        if account is not None:
            account.background_jobs_paused_at = None
            account.paused_reason = None


class CredentialRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def for_owner(self, owner_id: uuid.UUID) -> ProviderCredential | None:
        result = await self._session.execute(
            select(ProviderCredential).where(ProviderCredential.owner_id == owner_id)
        )
        return result.scalar_one_or_none()

    def add(self, credential: ProviderCredential) -> None:
        self._session.add(credential)

    async def delete_for_owner(self, owner_id: uuid.UUID) -> None:
        existing = await self.for_owner(owner_id)
        if existing is not None:
            await self._session.delete(existing)


class BudgetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def for_owner(self, owner_id: uuid.UUID) -> AiUsageBudget | None:
        result = await self._session.execute(
            select(AiUsageBudget).where(AiUsageBudget.owner_id == owner_id)
        )
        return result.scalar_one_or_none()

    def add(self, budget: AiUsageBudget) -> None:
        self._session.add(budget)

    async def spent_since(self, owner_id: uuid.UUID, since: date) -> Decimal:
        result = await self._session.execute(
            select(func.coalesce(func.sum(AiUsageLedger.cost_usd), 0)).where(
                AiUsageLedger.owner_id == owner_id,
                AiUsageLedger.occurred_at
                >= datetime(since.year, since.month, since.day, tzinfo=utcnow().tzinfo),
            )
        )
        return Decimal(result.scalar_one())

    def record(self, entry: AiUsageLedger) -> None:
        self._session.add(entry)
