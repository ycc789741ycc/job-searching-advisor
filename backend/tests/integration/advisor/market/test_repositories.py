"""The SQL side of the market's repository interfaces, against a real database.

What is worth proving here, beyond the use-case tests: every entity survives the
trip through its mapper, an owner scope sees one owner's rows and nobody else's,
and each domain event lands in the outbox under the name and payload the
dispatcher reads.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text

from advisor.market import SqlMarketUnitOfWork
from advisor.market.domain import (
    Company,
    CompanySubscription,
    Coverage,
    CrawlSource,
    JobPosting,
    MarketSelected,
    NormalizedPosting,
    PostingsChanged,
    PostingScope,
    PostingStatus,
    PrivateJobPosting,
    SalaryRange,
    SourceKind,
    SourceOrigin,
    SubscriptionAdded,
)
from kernel.db import Database

pytestmark = pytest.mark.integration


def _subscription(owner_id: uuid.UUID, company: Company) -> CompanySubscription:
    return CompanySubscription.new(
        owner_id=owner_id,
        company=company,
        role_title="Backend",
        role_id=None,
        url="https://acme.test/jobs",
        coverage=Coverage.MANUAL,
    )


async def test_a_subscription_round_trips_and_stays_with_its_owner(
    database: Database, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    uow = SqlMarketUnitOfWork(database)
    company = Company.named(f"Repo Co {uuid.uuid4().hex[:8]}")
    async with uow.shared() as market:
        await market.companies.add(company)
    stored = _subscription(account, company)

    async with uow.for_owner(account) as mine:
        await mine.subscriptions.add(stored)
    async with uow.for_owner(account) as mine:
        loaded = await mine.subscriptions.get(stored.id)
        assert loaded == stored
        assert loaded is not None
        loaded.resubscribe(role_id=None, url="https://acme.test/careers")
        loaded.last_refreshed_at = datetime(2026, 9, 27, tzinfo=UTC)
        await mine.subscriptions.save(loaded)
    async with uow.for_owner(account) as mine:
        assert await mine.subscriptions.find(company.id, "Backend") == loaded
        await mine.subscriptions.set_coverage(company.id, Coverage.CRAWLED)
    async with uow.for_owner(account) as mine:
        (only,) = await mine.subscriptions.at_company(company.id)
        assert only.coverage is Coverage.CRAWLED

    async with uow.for_owner(other_account) as theirs:
        assert await theirs.subscriptions.get(stored.id) is None
        assert await theirs.subscriptions.all() == []
        await theirs.subscriptions.remove(stored.id)
    async with uow.for_owner(account) as mine:
        assert await mine.subscriptions.get(stored.id) is not None


async def test_a_pasted_jd_and_its_vector_round_trip(
    database: Database, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    uow = SqlMarketUnitOfWork(database)
    pasted = PrivateJobPosting(
        id=uuid.uuid4(),
        owner_id=account,
        canonical_key=f"repo|backend|{uuid.uuid4().hex}",
        company_name="Repo Co",
        title="Backend",
        location=None,
        description="JD",
        url=None,
        shared_posting_id=None,
    )
    vector = [0.0] * 383 + [1.0]

    async with uow.for_owner(account) as mine:
        await mine.private_postings.add(pasted)
    async with uow.for_owner(account) as mine:
        assert await mine.private_postings.get(pasted.id) == pasted
        assert await mine.private_postings.vectors() == {}
        await mine.private_postings.set_vector(pasted.id, vector)
    async with uow.for_owner(account) as mine:
        assert await mine.private_postings.vectors() == {pasted.id: vector}
    async with uow.for_owner(other_account) as theirs:
        assert await theirs.private_postings.get(pasted.id) is None


async def test_shared_postings_round_trip_through_the_crawler_role(
    crawler_database: Database,
) -> None:
    uow = SqlMarketUnitOfWork(crawler_database)
    company = Company.named(f"Repo Co {uuid.uuid4().hex[:8]}")
    source = CrawlSource.board(
        kind="greenhouse",
        endpoint=f"https://boards.test/{uuid.uuid4()}",
        company_id=company.id,
        origin=SourceOrigin.DEMAND,
    )
    seen = NormalizedPosting(
        external_id="1",
        company_name=company.name,
        title="Backend",
        location="Berlin",
        description="Build things.",
        url="https://boards.test/1",
        source_kind=SourceKind.ATS_BOARD,
        posted_on=date(2026, 9, 1),
        salary=SalaryRange(min_amount=90_000, max_amount=120_000, currency="EUR"),
    )
    now = datetime(2026, 9, 27, 12, tzinfo=UTC)
    try:
        async with uow.shared() as market:
            await market.companies.add(company)
            await market.sources.add(source)
            posting = JobPosting.first_seen(
                seen, company_id=company.id, source_id=source.id, at=now
            )
            await market.postings.add(posting)

        async with uow.shared() as market:
            assert await market.companies.by_normalized_name(company.normalized_name) == company
            assert await market.sources.get(source.id) == source
            loaded = await market.postings.by_canonical_key(seen.canonical_key)
            assert loaded == posting
            assert loaded is not None
            loaded.seen_again(seen, source_id=source.id, at=now)
            await market.postings.save(loaded)
            assert await market.postings.salary_ranges([posting.id]) == [seen.salary]
            in_scope = await market.postings.open_in_scope(
                PostingScope(company_ids=(company.id,), markets=())
            )
            assert (loaded, company.name) in in_scope

        async with uow.shared() as market:
            assert await market.postings.expire_unseen(source.id, set()) == 1
        async with uow.shared() as market:
            expired = await market.postings.by_canonical_key(seen.canonical_key)
            assert expired is not None and expired.status is PostingStatus.EXPIRED
    finally:
        async with crawler_database.shared() as session:
            for table, column in (
                ("market.job_posting", "crawl_source_id"),
                ("market.crawl_source", "id"),
            ):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE {column} = :id"), {"id": source.id}
                )


async def test_owner_events_reach_the_outbox_as_the_dispatcher_reads_them(
    database: Database, account: uuid.UUID
) -> None:
    uow = SqlMarketUnitOfWork(database)
    company_id = uuid.uuid4()

    async with uow.for_owner(account) as mine:
        mine.record(SubscriptionAdded(owner_id=account, company_id=company_id, company_name="Acme"))
        mine.record(MarketSelected(owner_id=account, market="Berlin"))

    async with database.shared() as session:
        rows = await session.execute(
            text(
                "SELECT name, payload FROM outbox.event WHERE owner_id = :owner "
                "ORDER BY occurred_at"
            ),
            {"owner": account},
        )
        assert sorted(rows.all()) == [
            ("MarketSelected", {"market": "Berlin"}),
            ("SubscriptionAdded", {"company_id": str(company_id), "company_name": "Acme"}),
        ]


async def test_nothing_recorded_in_a_failed_scope_reaches_the_outbox(
    database: Database, account: uuid.UUID
) -> None:
    uow = SqlMarketUnitOfWork(database)
    with pytest.raises(RuntimeError):
        async with uow.for_owner(account) as mine:
            mine.record(MarketSelected(owner_id=account, market="Nowhere"))
            raise RuntimeError("the use case failed")

    async with database.shared() as session:
        rows = await session.execute(
            text("SELECT count(*) FROM outbox.event WHERE owner_id = :owner"), {"owner": account}
        )
        assert rows.scalar_one() == 0


async def test_a_market_event_carries_no_owner(
    crawler_database: Database, database: Database
) -> None:
    uow = SqlMarketUnitOfWork(crawler_database)
    market = f"Repo market {uuid.uuid4().hex[:8]}"

    async with uow.shared() as shared:
        shared.record(PostingsChanged(company_id=None, market=market, seen=2, expired=1))

    async with database.shared() as session:
        rows = await session.execute(
            text(
                "SELECT owner_id, payload FROM outbox.event "
                "WHERE name = 'PostingsChanged' AND payload->>'market' = :market"
            ),
            {"market": market},
        )
        owner_id, payload = rows.one()
    assert owner_id is None
    assert payload == {"company_id": None, "market": market, "seen": 2, "expired": 1}
