"""Worker handlers for the market module.

The one that matters is ``materialize_crawl_sources``: it copies the companies
and markets users asked for into ``market.crawl_source`` **without user ids**,
so the crawler cannot tell who asked for them.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from kernel.db.base import utcnow
from kernel.fetch import GuardedClient
from kernel.logging import get_logger
from modules.market.domain import Coverage, SourceKind
from modules.market.infra.models import Company, CompanySubscription, CrawlSource

log = get_logger(__name__)


async def discover_board(deps: Any, *, owner_id: str, company_id: str, company_name: str) -> None:
    """Look for a supported job board; fall back to manual coverage."""
    from crawler.discovery import discover_board as probe

    settings = deps.settings
    async with GuardedClient(
        timeout_seconds=settings.crawl_http_timeout_seconds,
        user_agent=settings.crawl_user_agent,
    ) as client:
        found = await probe(client, company_name)

    coverage = Coverage.CRAWLED if found is not None else Coverage.MANUAL
    await deps.market.set_coverage(uuid.UUID(owner_id), uuid.UUID(company_id), coverage)

    if found is not None:
        async with deps.database.shared() as session:
            existing = await session.execute(
                select(CrawlSource).where(CrawlSource.endpoint == found.endpoint)
            )
            if existing.scalar_one_or_none() is None:
                session.add(
                    CrawlSource(
                        kind=found.adapter_name,
                        company_id=uuid.UUID(company_id),
                        endpoint=found.endpoint,
                    )
                )
    log.info("market.board_discovered", company=company_name, coverage=str(coverage))


async def refresh_company(deps: Any, *, owner_id: str, company_id: str) -> None:
    """Re-crawl one watched company now, inside the per-day cap."""
    from crawler.run import crawl_one_source
    from modules.market.public import CrawlIngest

    ingest = CrawlIngest(deps.database)
    sources = [s for s in await ingest.due_sources() if str(s.company_id) == company_id]
    settings = deps.settings
    for source in sources:
        await crawl_one_source(
            ingest,
            source,
            user_agent=settings.crawl_user_agent,
            timeout_seconds=settings.crawl_http_timeout_seconds,
            rate_limit_per_second=settings.crawl_rate_limit_per_host_per_second,
        )

    async with deps.database.for_user(uuid.UUID(owner_id)) as session:
        rows = await session.execute(
            select(CompanySubscription).where(
                CompanySubscription.owner_id == uuid.UUID(owner_id),
                CompanySubscription.company_id == uuid.UUID(company_id),
            )
        )
        subscription = rows.scalar_one_or_none()
        if subscription is not None:
            subscription.last_refreshed_at = utcnow()


async def materialize_crawl_sources(deps: Any) -> None:
    """Refresh ``market.crawl_source`` from what users asked for.

    Deliberately loses the user ids on the way across: the crawler holds no
    user data and must not be able to infer any.
    """
    async with deps.database.shared() as session:
        wanted = await session.execute(
            select(CompanySubscription.company_id, CompanySubscription.company_name).distinct()
        )
        rows = wanted.all()

    added = 0
    for company_id, company_name in rows:
        async with deps.database.shared() as session:
            existing = await session.execute(
                select(CrawlSource).where(CrawlSource.company_id == company_id)
            )
            if existing.scalar_one_or_none() is not None:
                continue
            company = await session.get(Company, company_id)
            name = company.name if company is not None else company_name

        settings = deps.settings
        from crawler.discovery import discover_board as probe

        async with GuardedClient(
            timeout_seconds=settings.crawl_http_timeout_seconds,
            user_agent=settings.crawl_user_agent,
        ) as client:
            found = await probe(client, name)
        if found is None:
            continue
        async with deps.database.shared() as session:
            session.add(
                CrawlSource(kind=found.adapter_name, company_id=company_id, endpoint=found.endpoint)
            )
            added += 1

    log.info("market.crawl_sources_materialized", added=added, considered=len(rows))


__all__ = [
    "SourceKind",
    "discover_board",
    "materialize_crawl_sources",
    "refresh_company",
]
