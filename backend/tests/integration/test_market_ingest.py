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


# -- role subscriptions (domain decision 19) --------------------------------


async def test_a_user_can_watch_several_roles_at_one_company(
    database: Database, account: uuid.UUID
) -> None:
    from modules.market.public import Coverage

    market = MarketService(database, manual_refresh_per_day=3)
    company = f"Kestrel {uuid.uuid4().hex[:8]}"

    backend = await market.subscribe(
        account, company_name=company, role_title="Senior Backend Engineer"
    )
    await market.set_coverage(account, backend.company_id, Coverage.CRAWLED)
    platform = await market.subscribe(
        account,
        company_name=company,
        role_title="Staff Platform Engineer",
        url="https://jobs.lever.co/kestrel",
    )
    again = await market.subscribe(
        account,
        company_name=company,
        role_title="Senior Backend Engineer",
        url="https://boards.greenhouse.io/kestrel",
    )

    assert again.id == backend.id
    assert again.url == "https://boards.greenhouse.io/kestrel"
    assert platform.id != backend.id
    # Coverage belongs to the company's board, so the new role starts from it.
    assert platform.coverage is Coverage.CRAWLED
    mine = [s for s in await market.subscriptions(account) if s.company_name == company]
    assert sorted(s.role_title for s in mine) == [
        "Senior Backend Engineer",
        "Staff Platform Engineer",
    ]


async def test_unsubscribing_removes_only_that_role(
    database: Database, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    from kernel.errors import NotFoundError

    market = MarketService(database, manual_refresh_per_day=3)
    company = f"Fieldnote {uuid.uuid4().hex[:8]}"
    keep = await market.subscribe(account, company_name=company, role_title="Full-Stack")
    drop = await market.subscribe(account, company_name=company, role_title="Frontend")

    # Another user can neither see nor remove it.
    with pytest.raises(NotFoundError):
        await market.subscription(other_account, drop.id)
    await market.unsubscribe(other_account, drop.id)
    assert (await market.subscription(account, drop.id)).id == drop.id

    await market.unsubscribe(account, drop.id)
    remaining = [s.id for s in await market.subscriptions(account) if s.company_name == company]
    assert remaining == [keep.id]


async def test_a_subscription_needs_a_role_and_a_web_link(
    database: Database, account: uuid.UUID
) -> None:
    from kernel.errors import ValidationError

    market = MarketService(database, manual_refresh_per_day=3)
    with pytest.raises(ValidationError, match="role"):
        await market.subscribe(account, company_name="Acme", role_title="  ")
    with pytest.raises(ValidationError, match="http"):
        await market.subscribe(
            account, company_name="Acme", role_title="Engineer", url="file:///etc/passwd"
        )


async def test_a_company_change_reaches_each_watching_user_once(
    database: Database, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    """Two roles watched at one company still make one recluster, not two."""
    from types import SimpleNamespace

    from app.dispatcher import _users_affected_by

    market = MarketService(database, manual_refresh_per_day=3)
    company = f"Meridian {uuid.uuid4().hex[:8]}"
    first = await market.subscribe(account, company_name=company, role_title="Staff Platform")
    await market.subscribe(account, company_name=company, role_title="Senior Backend")
    await market.subscribe(other_account, company_name=company, role_title="SRE")

    affected = await _users_affected_by(
        SimpleNamespace(database=database),  # type: ignore[arg-type]
        {"company_id": str(first.company_id)},
    )
    assert sorted(affected) == sorted([account, other_account])


async def test_a_link_reaches_board_discovery_without_its_owner(
    database: Database,
    account: uuid.UUID,
    settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The crawler learns where to look, never who asked."""
    from types import SimpleNamespace

    import crawler.discovery
    from crawler.discovery import DiscoveredBoard
    from modules.market import jobs

    market = MarketService(database, manual_refresh_per_day=3)
    company = f"Northwind {uuid.uuid4().hex[:8]}"
    subscription = await market.subscribe(
        account,
        company_name=company,
        role_title="Senior Backend Engineer",
        url="https://boards.greenhouse.io/northwind-test",
    )

    probed: list[tuple[str, str | None]] = []
    endpoint = f"https://boards-api.greenhouse.io/v1/boards/{uuid.uuid4().hex}/jobs"

    async def fake_probe(client, company_name, *, url=None, user_agent="*", **_):
        probed.append((company_name, url))
        return DiscoveredBoard(adapter_name="greenhouse", endpoint=endpoint, posting_count=1)

    monkeypatch.setattr(crawler.discovery, "discover_board", fake_probe)
    await jobs.discover_board(
        SimpleNamespace(settings=settings, market=market, database=database),
        owner_id=str(account),
        company_id=str(subscription.company_id),
        company_name=company,
        url=subscription.url,
    )

    assert probed == [(company, "https://boards.greenhouse.io/northwind-test")]
    async with database.shared() as session:
        row = await session.execute(
            text("SELECT * FROM market.crawl_source WHERE endpoint = :endpoint"),
            {"endpoint": endpoint},
        )
        stored = row.mappings().one()
    assert stored["company_id"] == subscription.company_id
    assert not {"owner_id", "user_id", "url"} & set(stored.keys())
    async with database.shared() as session:
        await session.execute(
            text("DELETE FROM market.crawl_source WHERE endpoint = :endpoint"),
            {"endpoint": endpoint},
        )


async def test_the_weekly_recheck_sees_every_users_subscriptions(
    database: Database,
    account: uuid.UUID,
    settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Materialising crawl sources must read across users — through the fan-out
    policy — or it silently finds nothing to crawl."""
    from types import SimpleNamespace

    import crawler.discovery
    from crawler.discovery import DiscoveredBoard
    from modules.market import jobs

    market = MarketService(database, manual_refresh_per_day=3)
    company = f"Ostrom {uuid.uuid4().hex[:8]}"
    await market.subscribe(
        account,
        company_name=company,
        role_title="Platform Engineer",
        url="https://jobs.ashbyhq.com/ostrom-test",
    )
    endpoint = f"https://api.ashbyhq.com/posting-api/job-board/{uuid.uuid4().hex}"
    probed: list[tuple[str, str | None]] = []

    async def fake_probe(client, company_name, *, url=None, user_agent="*", **_):
        probed.append((company_name, url))
        if company_name != company:
            return None
        return DiscoveredBoard(adapter_name="ashby", endpoint=endpoint, posting_count=1)

    monkeypatch.setattr(crawler.discovery, "discover_board", fake_probe)
    await jobs.materialize_crawl_sources(SimpleNamespace(settings=settings, database=database))

    assert (company, "https://jobs.ashbyhq.com/ostrom-test") in probed
    async with database.shared() as session:
        found = await session.execute(
            text("SELECT count(*) FROM market.crawl_source WHERE endpoint = :endpoint"),
            {"endpoint": endpoint},
        )
        assert found.scalar_one() == 1
        await session.execute(
            text("DELETE FROM market.crawl_source WHERE endpoint = :endpoint"),
            {"endpoint": endpoint},
        )


# -- the baseline crawl (domain decision 15) --------------------------------


async def test_seeding_the_baseline_is_idempotent_and_retires_what_was_dropped(
    database: Database, crawler_database: Database
) -> None:
    from modules.market.public import BASELINE_SOURCES, BaselineSource

    extra = BaselineSource(
        "greenhouse",
        f"Baseline Test {uuid.uuid4().hex[:8]}",
        f"https://boards-api.greenhouse.io/v1/boards/{uuid.uuid4().hex}/jobs?content=true",
    )
    market = MarketService(database, manual_refresh_per_day=3)

    async def rows_for(endpoint: str) -> list[tuple[str, str]]:
        async with database.shared() as session:
            found = await session.execute(
                text("SELECT origin, status FROM market.crawl_source WHERE endpoint = :e"),
                {"e": endpoint},
            )
            return [tuple(row) for row in found.all()]

    try:
        await market.seed_baseline((*BASELINE_SOURCES, extra))
        await market.seed_baseline((*BASELINE_SOURCES, extra))
        assert await rows_for(extra.endpoint) == [("baseline", "active")]

        # Dropped from the list: retired, not deleted.
        _active, retired = await market.seed_baseline(BASELINE_SOURCES)
        assert retired == 1
        assert await rows_for(extra.endpoint) == [("baseline", "retired")]
        for source in BASELINE_SOURCES:
            assert await rows_for(source.endpoint) == [("baseline", "active")]
    finally:
        async with crawler_database.shared() as session:
            await session.execute(
                text("DELETE FROM market.crawl_source WHERE endpoint = :e"),
                {"e": extra.endpoint},
            )


async def test_a_user_with_no_market_sees_baseline_postings_and_one_with_a_market_does_not(
    database: Database,
    crawler_database: Database,
    account: uuid.UUID,
    other_account: uuid.UUID,
) -> None:
    company = f"Baseline Co {uuid.uuid4().hex[:8]}"
    async with crawler_database.shared() as session:
        row = CrawlSource(
            kind="greenhouse",
            endpoint=f"https://boards.test/{uuid.uuid4()}",
            origin="baseline",
        )
        session.add(row)
        await session.flush()
        source_id = row.id
    try:
        await CrawlIngest(crawler_database).record_crawl(
            source_id, [posting("Baseline Engineer", company=company, location="Lisbon")]
        )
        market = MarketService(database, manual_refresh_per_day=3)
        await market.add_market(other_account, f"Elsewhere {uuid.uuid4().hex[:8]}")

        mine = await market.postings_in_scope(account)
        theirs = await market.postings_in_scope(other_account)

        assert any(p.company_name == company for p in mine)
        assert all(p.company_name != company for p in theirs)
    finally:
        async with crawler_database.shared() as session:
            await session.execute(
                text("DELETE FROM market.job_posting WHERE crawl_source_id = :id"),
                {"id": source_id},
            )
            await session.execute(
                text("DELETE FROM market.crawl_source WHERE id = :id"), {"id": source_id}
            )


async def test_materialising_leaves_a_baseline_source_alone(
    database: Database,
    account: uuid.UUID,
    settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A watched company already on the baseline list gets no second source."""
    from types import SimpleNamespace

    import crawler.discovery
    from modules.market import jobs
    from modules.market.public import BASELINE_SOURCES

    baseline = BASELINE_SOURCES[0]
    market = MarketService(database, manual_refresh_per_day=3)
    await market.seed_baseline()
    await market.subscribe(account, company_name=baseline.company_name, role_title="Engineer")

    probed: list[str] = []

    async def record_probe(client, company_name, **_):
        probed.append(company_name)
        return None

    monkeypatch.setattr(crawler.discovery, "discover_board", record_probe)
    await jobs.materialize_crawl_sources(SimpleNamespace(settings=settings, database=database))

    assert baseline.company_name not in probed
    async with database.shared() as session:
        found = await session.execute(
            text(
                "SELECT origin, count(*) FROM market.crawl_source cs "
                "JOIN market.company c ON c.id = cs.company_id "
                "WHERE c.name = :name GROUP BY origin"
            ),
            {"name": baseline.company_name},
        )
        assert {origin: count for origin, count in found.all()} == {"baseline": 1}
