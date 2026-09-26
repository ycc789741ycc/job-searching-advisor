"""Builds the market component from the infrastructure handles it is given.

The composition root calls these; nothing else constructs a repository or a
unit of work (ADR 0011).
"""

from __future__ import annotations

from advisor.market.infra.unit_of_work import SqlAlchemyMarketUnitOfWork
from advisor.market.service import CrawlIngest, MarketService
from kernel.db import Database


def create_market_service(database: Database, *, manual_refresh_per_day: int) -> MarketService:
    return MarketService(
        SqlAlchemyMarketUnitOfWork(database), manual_refresh_per_day=manual_refresh_per_day
    )


def create_crawl_ingest(database: Database) -> CrawlIngest:
    """The crawler's view of the market: pass it the crawler role's database."""
    return CrawlIngest(SqlAlchemyMarketUnitOfWork(database))
