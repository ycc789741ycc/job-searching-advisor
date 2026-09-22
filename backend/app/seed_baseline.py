"""Loads the platform's baseline crawl list (domain decision 15).

Runs as the last step of ``make migrate``, after the schema is at head, so the
crawler's first run after an install already has sources to crawl. Idempotent:
running it again changes nothing, and an entry removed from the list is retired.
"""

from __future__ import annotations

import asyncio

from kernel.config import get_settings
from kernel.db import Database
from kernel.logging import get_logger
from modules.market.public import MarketService

log = get_logger(__name__)


async def main() -> None:
    settings = get_settings()
    database = Database(settings)
    try:
        market = MarketService(
            database, manual_refresh_per_day=settings.crawl_manual_refresh_per_day
        )
        active, retired = await market.seed_baseline()
    finally:
        await database.dispose()
    log.info("market.baseline_seeded", active=active, retired=retired)
    print(f"baseline crawl sources: {active} active, {retired} retired")


if __name__ == "__main__":
    asyncio.run(main())
