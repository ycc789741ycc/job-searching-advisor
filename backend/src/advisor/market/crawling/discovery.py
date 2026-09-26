"""Finding a company's job board.

When a user watches a role at a company, we look for a supported board. A
careers or JD URL they gave comes first: a board URL names its slug outright,
and any other page may carry schema.org ``JobPosting`` markup (domain decision
19). Then we guess slugs from the company name. If we find nothing, the
subscription is ``manual``: it says plainly that there are no automatic updates
and offers "paste a JD" instead. Each weekly crawl looks again, because
companies change hiring systems (domain decision 13).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit

from advisor.market.crawling.adapters import ATS_ADAPTERS, BY_NAME, BoardAdapter, JsonLdAdapter
from advisor.market.crawling.politeness import RateLimiter, RobotsCache
from advisor.market.crawling.run import fetch_source
from advisor.market.service import CrawlSourceView
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


# Public board URLs, by host, for the boards we have an adapter for. The slug
# is the path segment the pattern captures. Regional hosts are left out: their
# APIs live elsewhere, so the slug alone would point at the wrong board.
_BOARD_URLS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("boards.greenhouse.io", re.compile(r"^/([A-Za-z0-9_-]+)"), "greenhouse"),
    ("job-boards.greenhouse.io", re.compile(r"^/([A-Za-z0-9_-]+)"), "greenhouse"),
    ("boards-api.greenhouse.io", re.compile(r"^/v1/boards/([A-Za-z0-9_-]+)"), "greenhouse"),
    ("jobs.lever.co", re.compile(r"^/([A-Za-z0-9_-]+)"), "lever"),
    ("api.lever.co", re.compile(r"^/v0/postings/([A-Za-z0-9_-]+)"), "lever"),
    ("jobs.ashbyhq.com", re.compile(r"^/([A-Za-z0-9_.-]+)"), "ashby"),
    ("api.ashbyhq.com", re.compile(r"^/posting-api/job-board/([A-Za-z0-9_.-]+)"), "ashby"),
)


@dataclass(frozen=True, slots=True)
class BoardRef:
    adapter_name: str
    slug: str


def board_from_url(url: str) -> BoardRef | None:
    """The supported board a URL points at, read from the URL alone.

    No request is made: this only recognises the shape. ``None`` means the URL
    is not a board we know, which may still be a careers page with JSON-LD.
    """
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return None
    host = (parts.hostname or "").lower()
    for known_host, path, adapter_name in _BOARD_URLS:
        if host == known_host and (match := path.match(parts.path)):
            return BoardRef(adapter_name=adapter_name, slug=match.group(1))
    return None


@dataclass(frozen=True, slots=True)
class DiscoveredBoard:
    adapter_name: str
    endpoint: str
    posting_count: int


async def discover_board(
    client: GuardedClient,
    company_name: str,
    *,
    url: str | None = None,
    user_agent: str = "*",
    adapters: tuple[BoardAdapter, ...] = ATS_ADAPTERS,
) -> DiscoveredBoard | None:
    """Find a board for this company. ``None`` means manual coverage.

    A URL the user gave is tried first; then board slugs guessed from the name.
    """
    if url:
        ref = board_from_url(url)
        if ref is not None and ref.adapter_name in BY_NAME:
            found = await _probe(client, BY_NAME[ref.adapter_name], ref.slug, company_name)
            if found is not None:
                return found
        elif ref is None:
            found = await _json_ld_page(client, url, company_name, user_agent=user_agent)
            if found is not None:
                return found

    for adapter in adapters:
        for slug in candidate_slugs(company_name):
            found = await _probe(client, adapter, slug, company_name)
            if found is not None:
                return found
    return None


async def _probe(
    client: GuardedClient, adapter: BoardAdapter, slug: str, company_name: str
) -> DiscoveredBoard | None:
    endpoint = adapter.endpoint_for(slug)
    try:
        payload = await client.get_json(endpoint)
    except UpstreamFailedError:
        return None
    postings = adapter.parse(payload, company_name=company_name)
    if not postings:
        return None
    return DiscoveredBoard(
        adapter_name=adapter.name, endpoint=endpoint, posting_count=len(postings)
    )


async def _json_ld_page(
    client: GuardedClient, url: str, company_name: str, *, user_agent: str
) -> DiscoveredBoard | None:
    """A careers page that publishes ``JobPosting`` markup is a source too.

    Fetched the way the weekly crawl will fetch it — robots.txt first — so a
    page the crawl could not read is never reported as crawled.
    """
    source = CrawlSourceView(
        id=uuid.uuid4(),
        kind=JsonLdAdapter.name,
        endpoint=url,
        company_id=None,
        company_name=company_name,
        market=None,
    )
    try:
        postings = await fetch_source(
            client, source, robots=RobotsCache(user_agent), limiter=RateLimiter(per_second=0)
        )
    except UpstreamFailedError:
        return None
    if not postings:
        return None
    return DiscoveredBoard(
        adapter_name=JsonLdAdapter.name, endpoint=url, posting_count=len(postings)
    )
