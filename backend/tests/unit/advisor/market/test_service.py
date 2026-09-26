"""Market use cases against in-memory storage: what they decide, with no database."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest

from advisor.market import (
    BaselineSource,
    CrawlIngest,
    MarketService,
    NormalizedPosting,
    SalaryRange,
    SourceKind,
    Visibility,
)
from advisor.market.domain import (
    Company,
    Coverage,
    CrawlSource,
    MarketSelected,
    PostingsChanged,
    PostingStatus,
    SourceOrigin,
    SourceStatus,
    SubscriptionAdded,
)
from kernel.errors import NotFoundError, RateLimitedError, ValidationError
from tests.unit.advisor.market.fakes import FakeMarketUnitOfWork

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.UUID("00000000-0000-0000-0000-000000000002")


def _service(uow: FakeMarketUnitOfWork, *, per_day: int = 3) -> MarketService:
    return MarketService(uow, manual_refresh_per_day=per_day)


def _posting(title: str, *, company: str = "Acme", salary: SalaryRange | None = None):
    return NormalizedPosting(
        external_id=title,
        company_name=company,
        title=title,
        location="Berlin",
        description=f"{title} description",
        url=f"https://acme.test/{title}",
        source_kind=SourceKind.ATS_BOARD,
        posted_on=date(2026, 9, 1),
        salary=salary,
    )


# --- subscriptions ---------------------------------------------------------


async def test_a_new_subscription_is_announced_once() -> None:
    uow = FakeMarketUnitOfWork()
    market = _service(uow)

    first = await market.subscribe(OWNER, company_name=" Acme ", role_title="Backend")
    again = await market.subscribe(
        OWNER, company_name="acme", role_title="Backend", url="https://acme.test/jobs"
    )

    assert again.id == first.id
    assert again.url == "https://acme.test/jobs"
    assert uow.store.events == [
        SubscriptionAdded(owner_id=OWNER, company_id=first.company_id, company_name="Acme")
    ]
    assert len(uow.store.companies) == 1


async def test_a_new_role_at_a_watched_company_inherits_its_coverage() -> None:
    uow = FakeMarketUnitOfWork()
    market = _service(uow)
    first = await market.subscribe(OWNER, company_name="Acme", role_title="Backend")
    await market.set_coverage(OWNER, first.company_id, Coverage.CRAWLED)

    second = await market.subscribe(OWNER, company_name="Acme", role_title="SRE")

    assert second.coverage is Coverage.CRAWLED


@pytest.mark.parametrize(
    ("company", "role", "url"),
    [("  ", "Backend", None), ("Acme", " ", None), ("Acme", "Backend", "ftp://acme.test")],
)
async def test_a_subscription_needs_a_company_a_role_and_a_web_link(
    company: str, role: str, url: str | None
) -> None:
    uow = FakeMarketUnitOfWork()
    with pytest.raises(ValidationError):
        await _service(uow).subscribe(OWNER, company_name=company, role_title=role, url=url)
    assert uow.store.subscriptions == {}


async def test_another_users_subscription_is_not_found() -> None:
    uow = FakeMarketUnitOfWork()
    market = _service(uow)
    theirs = await market.subscribe(OTHER, company_name="Acme", role_title="Backend")

    with pytest.raises(NotFoundError):
        await market.subscription(OWNER, theirs.id)
    await market.unsubscribe(OWNER, theirs.id)

    assert theirs.id in uow.store.subscriptions


async def test_a_refresh_marks_every_role_at_that_company() -> None:
    uow = FakeMarketUnitOfWork()
    market = _service(uow)
    backend = await market.subscribe(OWNER, company_name="Acme", role_title="Backend")
    await market.subscribe(OWNER, company_name="Acme", role_title="SRE")
    elsewhere = await market.subscribe(OWNER, company_name="Globex", role_title="Backend")

    await market.mark_refreshed(OWNER, backend.company_id)

    refreshed = {
        (s.company_name, s.role_title): s.last_refreshed_at
        for s in await market.subscriptions(OWNER)
    }
    assert refreshed[("Acme", "Backend")] is not None
    assert refreshed[("Acme", "SRE")] is not None
    assert refreshed[("Globex", "Backend")] is None
    assert uow.store.subscriptions[elsewhere.id].last_refreshed_at is None


# --- markets ---------------------------------------------------------------


async def test_choosing_a_market_twice_announces_it_once() -> None:
    uow = FakeMarketUnitOfWork()
    market = _service(uow)

    await market.add_market(OWNER, " Berlin ")
    chosen = await market.add_market(OWNER, "Berlin")

    assert chosen == ["Berlin"]
    assert uow.store.events == [MarketSelected(owner_id=OWNER, market="Berlin")]


async def test_the_fan_out_finds_watchers_of_a_company_or_a_market() -> None:
    uow = FakeMarketUnitOfWork()
    market = _service(uow)
    watched = await market.subscribe(OWNER, company_name="Acme", role_title="Backend")
    await market.add_market(OTHER, "Berlin")

    assert await market.owners_affected_by(company_id=watched.company_id) == [OWNER]
    assert await market.owners_affected_by(market="Berlin") == [OTHER]
    assert await market.owners_affected_by(
        company_id=watched.company_id, market="Berlin"
    ) == sorted([OWNER, OTHER])


# --- manual refresh --------------------------------------------------------


async def test_manual_refreshes_stop_at_the_daily_cap() -> None:
    uow = FakeMarketUnitOfWork()
    market = _service(uow, per_day=2)
    company = uuid.uuid4()

    await market.request_manual_refresh(OWNER, company)
    await market.request_manual_refresh(OWNER, company)
    with pytest.raises(RateLimitedError):
        await market.request_manual_refresh(OWNER, company)
    # The cap is per user.
    await market.request_manual_refresh(OTHER, company)


# --- crawling --------------------------------------------------------------


def _source(
    uow: FakeMarketUnitOfWork, *, origin: SourceOrigin = SourceOrigin.DEMAND
) -> CrawlSource:
    seeded_at = datetime(2026, 1, 1, tzinfo=UTC)
    company = Company.named("Acme")
    company.created_at = seeded_at
    uow.store.companies[company.id] = company
    source = CrawlSource.board(
        kind="greenhouse", endpoint="https://boards.test/acme", company_id=company.id, origin=origin
    )
    source.created_at = seeded_at
    uow.store.sources[source.id] = source
    return source


async def test_a_crawl_upserts_what_it_saw_and_expires_what_it_did_not() -> None:
    uow = FakeMarketUnitOfWork()
    ingest = CrawlIngest(uow)
    source = _source(uow)

    await ingest.record_crawl(source.id, [_posting("Backend"), _posting("SRE")])
    upserted, expired = await ingest.record_crawl(source.id, [_posting("Backend")])

    assert (upserted, expired) == (1, 1)
    status = {p.title: p.status for p in uow.store.postings.values()}
    assert status == {"Backend": PostingStatus.OPEN, "SRE": PostingStatus.EXPIRED}
    assert uow.store.events[-1] == PostingsChanged(
        company_id=source.company_id, market=None, seen=1, expired=1
    )


async def test_a_repeat_sighting_keeps_published_pay_it_no_longer_shows() -> None:
    uow = FakeMarketUnitOfWork()
    ingest = CrawlIngest(uow)
    source = _source(uow)
    pay = SalaryRange(min_amount=90_000, max_amount=120_000, currency="EUR")

    await ingest.record_crawl(source.id, [_posting("Backend", salary=pay)])
    await ingest.record_crawl(source.id, [_posting("Backend")])

    (posting,) = uow.store.postings.values()
    assert posting.salary == pay
    assert posting.crawl_source_id == source.id


async def test_a_failed_crawl_is_recorded_and_changes_nothing_else() -> None:
    uow = FakeMarketUnitOfWork()
    ingest = CrawlIngest(uow)
    source = _source(uow)

    assert await ingest.record_crawl(source.id, [], error="timeout") == (0, 0)

    assert uow.store.sources[source.id].last_error == "timeout"
    assert uow.store.sources[source.id].last_fetched_at is not None
    assert uow.store.events == []


async def test_a_crawl_of_an_unknown_source_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        await CrawlIngest(FakeMarketUnitOfWork()).record_crawl(uuid.uuid4(), [])


async def test_embedding_text_leads_with_the_title_twice() -> None:
    uow = FakeMarketUnitOfWork()
    ingest = CrawlIngest(uow)
    source = _source(uow)
    await ingest.record_crawl(source.id, [_posting("Backend")])

    [(posting_id, text)] = await ingest.postings_needing_embeddings("model")
    assert text == "Backend\nBackend\nBerlin\nBackend description"

    await ingest.store_embeddings("model", {posting_id: [0.1, 0.2]})
    assert await ingest.postings_needing_embeddings("model") == []


# --- scope -----------------------------------------------------------------


async def test_without_markets_the_scope_falls_back_to_baseline_postings() -> None:
    uow = FakeMarketUnitOfWork()
    ingest, market = CrawlIngest(uow), _service(uow)
    baseline = _source(uow, origin=SourceOrigin.BASELINE)
    await ingest.record_crawl(baseline.id, [_posting("Backend")])

    in_scope = await market.postings_in_scope(OWNER)
    assert [p.title for p in in_scope] == ["Backend"]

    # With a market chosen, only postings in it count, baseline or not.
    await market.add_market(OWNER, "Lisbon")
    assert await market.postings_in_scope(OWNER) == []


async def test_a_pasted_jd_is_private_and_links_to_its_crawled_twin() -> None:
    uow = FakeMarketUnitOfWork()
    ingest, market = CrawlIngest(uow), _service(uow)
    await ingest.record_crawl(_source(uow).id, [_posting("Backend")])

    pasted = await market.paste_job_description(
        OWNER, company_name="Acme", title="Backend", location="Berlin", description="JD"
    )

    assert pasted.visibility is Visibility.PRIVATE
    (stored,) = uow.store.private_postings.values()
    (crawled,) = uow.store.postings.values()
    assert stored.shared_posting_id == crawled.id
    assert await market.private_postings(OTHER) == []


# --- baseline and demand sources -------------------------------------------


async def test_seeding_the_baseline_retires_what_is_no_longer_listed() -> None:
    uow = FakeMarketUnitOfWork()
    market = _service(uow)
    kept = BaselineSource(kind="lever", company_name="Kept", endpoint="https://lever.test/kept")
    dropped = BaselineSource(kind="lever", company_name="Gone", endpoint="https://lever.test/gone")

    assert await market.seed_baseline((kept, dropped)) == (2, 0)
    assert await market.seed_baseline((kept,)) == (1, 1)
    assert await market.seed_baseline((kept,)) == (1, 0)

    status = {s.endpoint: s.status for s in uow.store.sources.values()}
    assert status == {kept.endpoint: SourceStatus.ACTIVE, dropped.endpoint: SourceStatus.RETIRED}


async def test_a_demand_board_becomes_baseline_when_listed() -> None:
    uow = FakeMarketUnitOfWork()
    market = _service(uow)
    watched = await market.subscribe(OWNER, company_name="Acme", role_title="Backend")
    await market.register_board(watched.company_id, kind="lever", endpoint="https://lever.test/a")
    await market.register_board(watched.company_id, kind="lever", endpoint="https://lever.test/a")

    await market.seed_baseline(
        (BaselineSource(kind="lever", company_name="Acme", endpoint="https://lever.test/a"),)
    )

    (source,) = uow.store.sources.values()
    assert source.origin is SourceOrigin.BASELINE
    assert source.company_id == watched.company_id


async def test_watched_boards_carry_one_link_per_company_and_no_owner() -> None:
    uow = FakeMarketUnitOfWork()
    market = _service(uow)
    await market.subscribe(OWNER, company_name="Acme", role_title="Backend")
    await market.subscribe(OTHER, company_name="Acme", role_title="SRE", url="https://acme.test")

    [(company_id, name, url)] = await market.watched_boards()

    assert name == "Acme" and url == "https://acme.test"
    assert await market.company_needing_source(company_id, "Acme") == "Acme"
    await market.add_demand_source(company_id, kind="lever", endpoint="https://lever.test/acme")
    assert await market.company_needing_source(company_id, "Acme") is None
