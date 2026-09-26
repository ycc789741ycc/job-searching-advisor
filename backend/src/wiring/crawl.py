"""The crawler's wiring: the crawler role's connection and nothing else.

Kept apart from ``wiring.container`` so the crawler process never imports the
rest of the application. No object store, no gateway, no credential access —
this process holds no secrets by design.
"""

from __future__ import annotations

from advisor.market import CrawlIngest, SqlMarketUnitOfWork
from kernel.config import Settings, Unit, get_settings
from kernel.db import Database


def build_crawl_ingest(settings: Settings | None = None) -> tuple[Database, CrawlIngest]:
    settings = settings or get_settings()
    settings.require_for(Unit.CRAWLER)
    database = Database(settings, url=settings.require_crawler_database_url())
    return database, CrawlIngest(SqlMarketUnitOfWork(database))
