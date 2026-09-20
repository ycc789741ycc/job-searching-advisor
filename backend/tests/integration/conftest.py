"""Integration fixtures.

These tests assume infra is already up and migrated. They never start infra
themselves — a missing database fails with the command to run, rather than
quietly booting something.

Each test cleans up after itself, so the suite is re-runnable without a
destructive reset.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from kernel.config import Settings, get_settings
from kernel.db import Database

pytestmark = pytest.mark.integration

REQUIRED_ENV = ("DATABASE_URL", "CRAWLER_DATABASE_URL", "MASTER_ENCRYPTION_KEY")


def _require_env() -> None:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        pytest.fail(
            f"missing {', '.join(missing)}. Integration tests read .env — run them "
            "through `make test-integration`.",
            pytrace=False,
        )


@pytest.fixture(scope="session")
def settings() -> Settings:
    _require_env()
    get_settings.cache_clear()
    return get_settings()


@pytest_asyncio.fixture
async def database(settings: Settings) -> AsyncIterator[Database]:
    db = Database(settings)
    try:
        async with db.shared() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        await db.dispose()
        pytest.fail(
            f"could not reach Postgres ({exc.__class__.__name__}). Run `make start-infra` first.",
            pytrace=False,
        )
    yield db
    await db.dispose()


@pytest_asyncio.fixture
async def crawler_engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    """A connection with the crawler's least-privilege role."""
    engine = create_async_engine(str(settings.crawler_database_url), poolclass=None)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def crawler_database(settings: Settings) -> AsyncIterator[Database]:
    """A Database on the crawler role — how CrawlIngest is wired in production."""
    db = Database(settings, url=str(settings.crawler_database_url))
    yield db
    await db.dispose()


@pytest_asyncio.fixture
async def account(database: Database) -> AsyncIterator[uuid.UUID]:
    """A throwaway account, removed afterwards along with everything it owns."""
    account_id = uuid.uuid4()
    async with database.shared() as session:
        await session.execute(
            text(
                "INSERT INTO identity.account (id, auth_subject, email, created_at, updated_at) "
                "VALUES (:id, :subject, :email, now(), now())"
            ),
            {"id": account_id, "subject": f"test|{account_id}", "email": "test@example.invalid"},
        )
    yield account_id
    await _purge(database, account_id)


@pytest_asyncio.fixture
async def other_account(database: Database) -> AsyncIterator[uuid.UUID]:
    account_id = uuid.uuid4()
    async with database.shared() as session:
        await session.execute(
            text(
                "INSERT INTO identity.account (id, auth_subject, email, created_at, updated_at) "
                "VALUES (:id, :subject, :email, now(), now())"
            ),
            {"id": account_id, "subject": f"test|{account_id}", "email": "other@example.invalid"},
        )
    yield account_id
    await _purge(database, account_id)


async def _purge(database: Database, account_id: uuid.UUID) -> None:
    from app.models import OWNER_ZONE_TABLES

    async with database.for_user(account_id) as session:
        for table in OWNER_ZONE_TABLES:
            await session.execute(
                text(f"DELETE FROM {table} WHERE owner_id = :owner"), {"owner": account_id}
            )
    async with database.shared() as session:
        await session.execute(
            text("DELETE FROM outbox.event WHERE owner_id = :owner"), {"owner": account_id}
        )
        await session.execute(
            text("DELETE FROM identity.account WHERE id = :id"), {"id": account_id}
        )


@pytest.fixture
def default_cap() -> Decimal:
    return Decimal("20")
