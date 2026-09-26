"""The SQLAlchemy side of the market's repositories, against a real database.

What is worth proving here, beyond the use-case tests:
- every entity survives the trip through its mapper;
- the six methods keep their contract: newest first, paging, counting, and
  not-found from ``update`` and ``delete``;
- an owner scope sees one owner's rows and nobody else's;
- each domain event lands in the outbox under the name and payload the
  dispatcher reads.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text

from advisor.market.domain import (
    Company,
    CompanyFilter,
    CompanySubscription,
    Coverage,
    CrawlSource,
    CrawlSourceFilter,
    JobPosting,
    JobPostingFilter,
    ManualRefresh,
    ManualRefreshFilter,
    MarketPreference,
    MarketPreferenceFilter,
    MarketSelected,
    NormalizedPosting,
    PostingEmbedding,
    PostingEmbeddingFilter,
    PostingsChanged,
    PostingScope,
    PostingStatus,
    PrivateJobPosting,
    PrivateJobPostingFilter,
    SalaryRange,
    SourceKind,
    SourceOrigin,
    SubscriptionAdded,
    SubscriptionFilter,
)
from advisor.market.infra.unit_of_work import SqlAlchemyMarketUnitOfWork
from kernel.db import Database
from kernel.errors import NotFoundError, ValidationError

pytestmark = pytest.mark.integration


async def _company(uow: SqlAlchemyMarketUnitOfWork) -> Company:
    async with uow.shared() as market:
        return await market.companies.create(Company.named(f"Repo Co {uuid.uuid4().hex[:8]}"))


def _subscription(owner_id: uuid.UUID, company: Company, role: str) -> CompanySubscription:
    return CompanySubscription.new(
        owner_id=owner_id,
        company=company,
        role_title=role,
        role_id=None,
        url="https://acme.test/jobs",
        coverage=Coverage.MANUAL,
    )


async def test_the_six_methods_keep_their_contract(database: Database, account: uuid.UUID) -> None:
    uow = SqlAlchemyMarketUnitOfWork(database)
    company = await _company(uow)

    # One transaction each: created_at is the transaction's start time.
    created = []
    for role in ("First", "Second", "Third"):
        async with uow.for_owner(account) as mine:
            created.append(await mine.subscriptions.create(_subscription(account, company, role)))
    assert all(s.created_at is not None and s.updated_at is not None for s in created)

    async with uow.for_owner(account) as mine:
        everything = SubscriptionFilter(company_id=company.id)
        newest_first = await mine.subscriptions.get_list(everything)
        assert [s.role_title for s in newest_first] == ["Third", "Second", "First"]
        assert newest_first[-1] == created[0]
        assert [s.role_title for s in await mine.subscriptions.get_list(everything, 2, 2)] == [
            "First"
        ]
        assert await mine.subscriptions.get_count(everything) == 3
        assert (
            await mine.subscriptions.get_count(
                SubscriptionFilter(company_id=company.id, role_title="Second")
            )
            == 1
        )
        with pytest.raises(ValidationError):
            await mine.subscriptions.get_list(everything, page=2)

        first = created[0]
        first.resubscribe(role_id=None, url="https://acme.test/careers")
        first.last_refreshed_at = datetime(2026, 9, 27, tzinfo=UTC)
        updated = await mine.subscriptions.update(first)
        assert updated.url == "https://acme.test/careers"
        assert await mine.subscriptions.get(first.id) == updated

        await mine.subscriptions.delete(first.id)
        assert await mine.subscriptions.get(first.id) is None
        with pytest.raises(NotFoundError):
            await mine.subscriptions.delete(first.id)
        with pytest.raises(NotFoundError):
            await mine.subscriptions.update(first)


async def test_an_owner_scope_sees_nobody_elses_rows(
    database: Database, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    uow = SqlAlchemyMarketUnitOfWork(database)
    company = await _company(uow)
    async with uow.for_owner(account) as mine:
        subscription = await mine.subscriptions.create(_subscription(account, company, "Backend"))
        preference = await mine.markets.create(
            MarketPreference.chosen(owner_id=account, market="Berlin")
        )

    async with uow.for_owner(other_account) as theirs:
        assert await theirs.subscriptions.get(subscription.id) is None
        assert await theirs.subscriptions.get_list(SubscriptionFilter()) == []
        assert await theirs.markets.get_count(MarketPreferenceFilter()) == 0
        with pytest.raises(NotFoundError):
            await theirs.markets.delete(preference.id)

    # The fan-out scope reads across users, for the dispatcher.
    async with uow.fanout() as everyone:
        watching = await everyone.subscriptions.get_list(SubscriptionFilter(company_id=company.id))
        assert [s.owner_id for s in watching] == [account]


async def test_pasted_jds_and_manual_refreshes_round_trip(
    database: Database, account: uuid.UUID
) -> None:
    uow = SqlAlchemyMarketUnitOfWork(database)
    vector = [0.0] * 383 + [1.0]

    async with uow.for_owner(account) as mine:
        pasted = await mine.private_postings.create(
            PrivateJobPosting.pasted(
                owner_id=account,
                company_name=" Repo Co ",
                title="Backend",
                location=None,
                description="JD",
                url=None,
                shared_posting_id=None,
            )
        )
        refresh = await mine.refreshes.create(
            ManualRefresh.requested(owner_id=account, company_id=uuid.uuid4())
        )
    assert refresh.requested_at is not None

    async with uow.for_owner(account) as mine:
        assert await mine.private_postings.get(pasted.id) == pasted
        assert await mine.private_postings.get_count(PrivateJobPostingFilter(has_vector=True)) == 0
        pasted.vector = vector
        await mine.private_postings.update(pasted)
        [embedded] = await mine.private_postings.get_list(PrivateJobPostingFilter(has_vector=True))
        assert embedded.vector == vector
        assert (
            await mine.refreshes.get_count(
                ManualRefreshFilter(requested_since=refresh.requested_at)
            )
            == 1
        )


async def test_shared_postings_round_trip_through_the_crawler_role(
    crawler_database: Database,
) -> None:
    uow = SqlAlchemyMarketUnitOfWork(crawler_database)
    seen_at = datetime(2026, 9, 27, 12, tzinfo=UTC)
    async with uow.shared() as market:
        company = await market.companies.create(Company.named(f"Repo Co {uuid.uuid4().hex[:8]}"))
        source = await market.sources.create(
            CrawlSource.board(
                kind="greenhouse",
                endpoint=f"https://boards.test/{uuid.uuid4()}",
                company_id=company.id,
                origin=SourceOrigin.DEMAND,
            )
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
    try:
        async with uow.shared() as market:
            posting = await market.postings.create(
                JobPosting.first_seen(seen, company_id=company.id, source_id=source.id, at=seen_at)
            )

        async with uow.shared() as market:
            assert await market.companies.get_list(
                CompanyFilter(normalized_name=company.normalized_name)
            ) == [company]
            assert await market.sources.get_list(CrawlSourceFilter(endpoint=source.endpoint)) == [
                source
            ]
            [loaded] = await market.postings.get_list(
                JobPostingFilter(canonical_key=seen.canonical_key)
            )
            assert loaded == posting
            assert (
                await market.postings.get_count(
                    JobPostingFilter(ids=(posting.id,), has_salary=True)
                )
                == 1
            )
            assert posting in await market.postings.get_open_in_scope(
                PostingScope(company_ids=(company.id,), markets=())
            )

            assert (
                await market.postings.get_count(
                    JobPostingFilter(ids=(posting.id,), missing_embedding_for="model")
                )
                == 1
            )
            await market.embeddings.create(
                PostingEmbedding(posting_id=posting.id, model_name="model", vector=[0.5] * 384)
            )
            assert (
                await market.postings.get_count(
                    JobPostingFilter(ids=(posting.id,), missing_embedding_for="model")
                )
                == 0
            )
            [embedding] = await market.embeddings.get_list(
                PostingEmbeddingFilter(posting_ids=(posting.id,), model_name="model")
            )
            assert embedding.vector == [0.5] * 384

        async with uow.shared() as market:
            assert await market.postings.expire_unseen(source.id, set()) == 1
        async with uow.shared() as market:
            expired = await market.postings.get(posting.id)
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
    uow = SqlAlchemyMarketUnitOfWork(database)
    company_id = uuid.uuid4()

    async with uow.for_owner(account) as mine:
        mine.record(SubscriptionAdded(owner_id=account, company_id=company_id, company_name="Acme"))
        mine.record(MarketSelected(owner_id=account, market="Berlin"))

    async with database.shared() as session:
        rows = await session.execute(
            text("SELECT name, payload FROM outbox.event WHERE owner_id = :owner"),
            {"owner": account},
        )
        assert sorted(rows.all()) == [
            ("MarketSelected", {"market": "Berlin"}),
            ("SubscriptionAdded", {"company_id": str(company_id), "company_name": "Acme"}),
        ]


async def test_nothing_recorded_in_a_failed_scope_reaches_the_outbox(
    database: Database, account: uuid.UUID
) -> None:
    uow = SqlAlchemyMarketUnitOfWork(database)
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
    uow = SqlAlchemyMarketUnitOfWork(crawler_database)
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
