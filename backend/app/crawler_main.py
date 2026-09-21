"""The ``crawler`` deployable.

Its own process on purpose: it parses hostile HTML from the internet, it runs
on a different schedule, and it holds no secrets and reads no user data. Its
database connection uses the ``crawler_rw`` role, which has no grant on any
user schema — a mistake here fails at the database rather than leaking.
"""

from __future__ import annotations

import asyncio

from app.container import build_crawl_ingest
from crawler.run import crawl_all
from kernel.config import Unit, get_settings
from kernel.logging import configure_logging, get_logger

log = get_logger(__name__)

WEEKLY_SECONDS = 7 * 24 * 60 * 60


async def run_once() -> None:
    settings = get_settings()
    database, ingest = build_crawl_ingest(settings)
    try:
        outcomes = await crawl_all(
            ingest,
            user_agent=settings.crawl_user_agent,
            timeout_seconds=settings.crawl_http_timeout_seconds,
            rate_limit_per_second=settings.crawl_rate_limit_per_host_per_second,
            embedding_model=settings.embedding_model_name,
        )
        log.info(
            "crawl.completed",
            sources=len(outcomes),
            failed=sum(1 for o in outcomes if o.error),
            upserted=sum(o.upserted for o in outcomes),
            expired=sum(o.expired for o in outcomes),
        )
    finally:
        await database.dispose()


async def main() -> None:
    settings = get_settings()
    configure_logging(f"{settings.service_name}-crawler", settings.log_level)
    # Missing configuration fails here, at startup, not at first use.
    settings.require_for(Unit.CRAWLER)
    # One weekly crawl covers subscribed company boards and market-wide APIs.
    while True:
        await run_once()
        await asyncio.sleep(WEEKLY_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
