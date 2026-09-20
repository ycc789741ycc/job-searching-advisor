"""Finding a company's job board.

When a user watches a company, we look for a supported board. If we find none,
the subscription is ``manual``: it says plainly that there are no automatic
updates and offers "paste a JD" instead. Each weekly crawl looks again, because
companies change hiring systems (domain decision 13).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from crawler.adapters import ATS_ADAPTERS, BoardAdapter
from kernel.errors import UpstreamFailedError
from kernel.fetch import GuardedClient

_SLUG = re.compile(r"[^a-z0-9]+")


def candidate_slugs(company_name: str) -> list[str]:
    """Board slugs a company is likely to use, most likely first."""
    base = _SLUG.sub("", company_name.lower())
    hyphenated = _SLUG.sub("-", company_name.lower()).strip("-")
    seen: list[str] = []
    for slug in (base, hyphenated):
        if slug and slug not in seen:
            seen.append(slug)
    return seen


@dataclass(frozen=True, slots=True)
class DiscoveredBoard:
    adapter_name: str
    endpoint: str
    posting_count: int


async def discover_board(
    client: GuardedClient, company_name: str, *, adapters: tuple[BoardAdapter, ...] = ATS_ADAPTERS
) -> DiscoveredBoard | None:
    """Probe the supported ATS boards. ``None`` means manual coverage."""
    for adapter in adapters:
        for slug in candidate_slugs(company_name):
            endpoint = adapter.endpoint_for(slug)
            try:
                payload = await client.get_json(endpoint)
            except UpstreamFailedError:
                continue
            postings = adapter.parse(payload, company_name=company_name)
            if postings:
                return DiscoveredBoard(
                    adapter_name=adapter.name,
                    endpoint=endpoint,
                    posting_count=len(postings),
                )
    return None
