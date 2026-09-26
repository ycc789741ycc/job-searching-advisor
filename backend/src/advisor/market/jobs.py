"""Worker use cases for the market component.

The one that matters is ``materialize_crawl_sources``: it copies the companies
and markets users asked for into ``market.crawl_source`` **without user ids**,
so the crawler cannot tell who asked for them.
"""

from __future__ import annotations

import uuid
from typing import Any

from advisor.market.domain import Coverage, SourceKind
from kernel.fetch import GuardedClient
from kernel.logging import get_logger

log = get_logger(__name__)


async def discover_board(
    deps: Any,
    *,
    owner_id: str,
    company_id: str,
    company_name: str,
    url: str | None = None,
) -> None:
    """Look for a supported job board, starting from the link the user gave;
    fall back to manual coverage."""
    from advisor.market.crawling.discovery import discover_board as probe

    settings = deps.settings
    async with GuardedClient(
        timeout_seconds=settings.crawl_http_timeout_seconds,
        user_agent=settings.crawl_user_agent,
    ) as client:
        found = await probe(client, company_name, url=url, user_agent=settings.crawl_user_agent)

    coverage = Coverage.CRAWLED if found is not None else Coverage.MANUAL
    await deps.market.set_coverage(uuid.UUID(owner_id), uuid.UUID(company_id), coverage)

    if found is not None:
        await deps.market.register_board(
            uuid.UUID(company_id), kind=found.adapter_name, endpoint=found.endpoint
        )
    log.info("market.board_discovered", company=company_name, coverage=str(coverage))


async def refresh_company(deps: Any, *, owner_id: str, company_id: str) -> None:
    """Re-crawl one watched company now, inside the per-day cap."""
    from advisor.market.crawling.run import crawl_one_source

    settings = deps.settings
    # Writing postings needs the crawler role: app_rw is read-only on the shared
    # market zone, which is what keeps posting data owned by one writer.
    crawler_db, ingest = deps.open_crawl_ingest()
    try:
        sources = [s for s in await ingest.due_sources() if str(s.company_id) == company_id]
        for source in sources:
            await crawl_one_source(
                ingest,
                source,
                user_agent=settings.crawl_user_agent,
                timeout_seconds=settings.crawl_http_timeout_seconds,
                rate_limit_per_second=settings.crawl_rate_limit_per_host_per_second,
            )
    finally:
        await crawler_db.dispose()

    await deps.market.mark_refreshed(uuid.UUID(owner_id), uuid.UUID(company_id))


async def materialize_crawl_sources(deps: Any) -> None:
    """Refresh ``market.crawl_source`` from what users asked for.

    Deliberately loses the user ids on the way across: the crawler holds no
    user data and must not be able to infer any.

    Reading every user's subscriptions is a cross-user read, so it goes through
    the fan-out scope and its SELECT-only policy. The shared scope has no
    ``app.user_id`` and sees no owner-zone rows at all.
    """
    rows = await deps.market.watched_boards()

    added = 0
    for company_id, company_name, url in rows:
        name = await deps.market.company_needing_source(company_id, company_name)
        if name is None:
            continue

        settings = deps.settings
        from advisor.market.crawling.discovery import discover_board as probe

        async with GuardedClient(
            timeout_seconds=settings.crawl_http_timeout_seconds,
            user_agent=settings.crawl_user_agent,
        ) as client:
            found = await probe(client, name, url=url, user_agent=settings.crawl_user_agent)
        if found is None:
            continue
        await deps.market.add_demand_source(
            company_id, kind=found.adapter_name, endpoint=found.endpoint
        )
        added += 1

    log.info("market.crawl_sources_materialized", added=added, considered=len(rows))


__all__ = [
    "SourceKind",
    "discover_board",
    "materialize_crawl_sources",
    "refresh_company",
]
