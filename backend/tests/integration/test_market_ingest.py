"""The crawler's write path, against a real database.

Dedup, expiry and the privacy of pasted JDs are the things worth proving here;
they are the rules that quietly stop being true if someone refactors a query.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import text

from kernel.db import Database
from modules.market.infra.models import CrawlSource
from modules.market.public import (
    CrawlIngest,
    MarketService,
    NormalizedPosting,
    SourceKind,
    Visibility,
)

pytestmark = pytest.mark.integration


# Postings dedup globally by company + title + location, so each test needs its
# own company or it collides with rows another test left behind.
COMPANY = f"Testco {uuid.uuid4().hex[:8]}"


def posting(title: str, *, company: str = COMPANY, location: str | None = "Berlin"):
    return NormalizedPosting(
        external_id=title.lower().replace(" ", "-"),
        company_name=company,
        title=title,
        location=location,
        description=f"You will work on {title}.",
        url=f"https://boards.test/{title}",
        source_kind=SourceKind.ATS_BOARD,
        posted_on=date(2026, 9, 1),
        salary=None,
    )


@pytest_asyncio.fixture
async def source(crawler_database: Database):
    """A throwaway crawl source, created and cleaned up with the crawler role.

    app_rw cannot delete postings — only the crawler writes the shared zone —
    so the whole fixture lives on that connection.
    """
    async with crawler_database.shared() as session:
        row = CrawlSource(kind="greenhouse", endpoint=f"https://boards.test/{uuid.uuid4()}")
        session.add(row)
        await session.flush()
        source_id = row.id
    yield source_id
    async with crawler_database.shared() as session:
        await session.execute(
            text("DELETE FROM market.job_posting WHERE crawl_source_id = :id"),
            {"id": source_id},
        )
        await session.execute(
            text("DELETE FROM market.crawl_source WHERE id = :id"), {"id": source_id}
        )


async def test_a_crawl_stores_normalised_postings(crawler_database: Database, source) -> None:
    ingest = CrawlIngest(crawler_database)
    upserted, expired = await ingest.record_crawl(
        source, [posting("Senior Backend Engineer"), posting("Platform Engineer")]
    )
    assert (upserted, expired) == (2, 0)

    async with crawler_database.shared() as session:
        count = await session.execute(
            text("SELECT count(*) FROM market.job_posting WHERE crawl_source_id = :id"),
            {"id": source},
        )
        assert count.scalar_one() == 2


async def test_the_same_job_seen_twice_does_not_duplicate(
    database: Database, crawler_database: Database, source
) -> None:
    """The dedup key is what keeps one opening from becoming two."""
    ingest = CrawlIngest(crawler_database)
    await ingest.record_crawl(source, [posting("Senior Backend Engineer (m/f/d)")])
    await ingest.record_crawl(source, [posting("Senior Backend Engineer")])

    async with database.shared() as session:
        count = await session.execute(
            text("SELECT count(*) FROM market.job_posting WHERE crawl_source_id = :id"),
            {"id": source},
        )
        assert count.scalar_one() == 1


async def test_a_posting_missing_from_a_crawl_is_expired_not_deleted(
    database: Database, crawler_database: Database, source
) -> None:
    """Expired postings still count toward salary history."""
    ingest = CrawlIngest(crawler_database)
    await ingest.record_crawl(source, [posting("Senior Backend Engineer"), posting("Gone Role")])
    await ingest.record_crawl(source, [posting("Senior Backend Engineer")])

    async with database.shared() as session:
        rows = await session.execute(
            text(
                "SELECT title, status FROM market.job_posting "
                "WHERE crawl_source_id = :id ORDER BY title"
            ),
            {"id": source},
        )
        assert {title: status for title, status in rows.all()} == {
            "Gone Role": "expired",
            "Senior Backend Engineer": "open",
        }


async def test_a_crawl_emits_a_market_event_with_no_user_in_it(
    database: Database, crawler_database: Database, source
) -> None:
    """The crawler must not be able to say who its work was for."""
    ingest = CrawlIngest(crawler_database)
    await ingest.record_crawl(source, [posting("Senior Backend Engineer")])

    async with database.shared() as session:
        rows = await session.execute(
            text(
                "SELECT owner_id, payload FROM outbox.event "
                "WHERE name = 'PostingsChanged' ORDER BY occurred_at DESC LIMIT 1"
            )
        )
        owner_id, payload = rows.one()
    assert owner_id is None
    assert "owner" not in payload and "user" not in payload


async def test_a_pasted_jd_never_reaches_the_shared_tables(
    database: Database, account: uuid.UUID
) -> None:
    market = MarketService(database, manual_refresh_per_day=3)
    pasted = await market.paste_job_description(
        account,
        company_name="Uncrawlable Ltd",
        title="Staff Engineer",
        location="Remote EU",
        description="A JD the user pasted themselves.",
    )
    assert pasted.visibility is Visibility.PRIVATE

    async with database.shared() as session:
        leaked = await session.execute(
            text("SELECT count(*) FROM market.job_posting WHERE title = 'Staff Engineer'")
        )
        assert leaked.scalar_one() == 0


async def test_another_users_pasted_jd_is_not_in_my_scope(
    database: Database, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    market = MarketService(database, manual_refresh_per_day=3)
    await market.paste_job_description(
        other_account,
        company_name="Theirs",
        title="Their Private Role",
        location=None,
        description="Only for them.",
    )
    mine = await market.postings_in_scope(account)
    assert all(p.title != "Their Private Role" for p in mine)


async def test_the_manual_refresh_cap_is_enforced(database: Database, account: uuid.UUID) -> None:
    """The weekly schedule stays the norm."""
    from kernel.errors import RateLimitedError

    market = MarketService(database, manual_refresh_per_day=2)
    company = uuid.uuid4()
    await market.request_manual_refresh(account, company)
    await market.request_manual_refresh(account, company)
    with pytest.raises(RateLimitedError, match="weekly crawl still runs"):
        await market.request_manual_refresh(account, company)
