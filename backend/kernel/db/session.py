"""Database sessions, and the row-level-security contract around them.

Every unit of work over owner-zone data runs inside a transaction that has
``app.user_id`` set. The API sets it from the verified JWT; a worker sets it
from the job's user. Code that forgets simply sees no rows, because the RLS
policies compare against that setting.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.sql import text

from kernel.config import Settings

_APP_USER_SETTING = "app.user_id"


class Database:
    def __init__(self, settings: Settings, *, url: str | None = None) -> None:
        self._engine: AsyncEngine = create_async_engine(
            url or str(settings.database_url),
            pool_size=settings.db_pool_size,
            pool_pre_ping=True,
            connect_args={
                "server_settings": {
                    "statement_timeout": str(settings.db_statement_timeout_ms),
                    "application_name": settings.service_name,
                }
            },
        )
        self._sessionmaker = async_sessionmaker(
            self._engine, expire_on_commit=False, class_=AsyncSession
        )

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    async def dispose(self) -> None:
        await self._engine.dispose()

    @asynccontextmanager
    async def for_user(self, owner_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
        """A transaction scoped to one user, with RLS active.

        ``SET LOCAL`` ties the setting to this transaction, so a pooled
        connection can never leak one user's identity into the next request.
        """
        async with self._sessionmaker() as session, session.begin():
            await session.execute(
                text(f"SELECT set_config('{_APP_USER_SETTING}', :uid, true)"),
                {"uid": str(owner_id)},
            )
            yield session

    @asynccontextmanager
    async def fanout(self) -> AsyncIterator[AsyncSession]:
        """A transaction allowed to read *which* users watch a company or market.

        This is the only cross-user read in the system. It exists because the
        crawler must not know who its work is for, so the worker resolves that
        afterwards. The policy behind this setting covers two columns on two
        tables and nothing else.
        """
        async with self._sessionmaker() as session, session.begin():
            await session.execute(text("SELECT set_config('app.fanout', 'on', true)"))
            yield session

    @asynccontextmanager
    async def shared(self) -> AsyncIterator[AsyncSession]:
        """A transaction over shared-zone data only (market, outbox).

        ``app.user_id`` is deliberately left unset: owner-zone tables return
        nothing here, which is the behaviour we want if someone reaches for
        them by mistake.
        """
        async with self._sessionmaker() as session, session.begin():
            yield session
