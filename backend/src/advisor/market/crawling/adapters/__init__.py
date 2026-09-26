from advisor.market.crawling.adapters.ashby import AshbyAdapter
from advisor.market.crawling.adapters.base import BoardAdapter, parse_date, salary_from, strip_html
from advisor.market.crawling.adapters.greenhouse import GreenhouseAdapter
from advisor.market.crawling.adapters.json_ld import JsonLdAdapter
from advisor.market.crawling.adapters.lever import LeverAdapter

# Probed in order when discovering a board for a newly watched company.
ATS_ADAPTERS: tuple[BoardAdapter, ...] = (
    GreenhouseAdapter(),
    LeverAdapter(),
    AshbyAdapter(),
)

BY_NAME: dict[str, BoardAdapter] = {
    adapter.name: adapter for adapter in (*ATS_ADAPTERS, JsonLdAdapter())
}

__all__ = [
    "ATS_ADAPTERS",
    "BY_NAME",
    "AshbyAdapter",
    "BoardAdapter",
    "GreenhouseAdapter",
    "JsonLdAdapter",
    "LeverAdapter",
    "parse_date",
    "salary_from",
    "strip_html",
]
