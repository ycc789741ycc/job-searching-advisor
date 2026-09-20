"""One crawl run.

Fetch each due source, normalise, dedup, expire what has gone, then embed.
The crawler never works out which users are affected — that would need user
data it has no grant on. It emits events about markets and companies, and the
worker fans them out (docs/technical_boundaries.md section 2).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from crawler.adapters import BY_NAME
from crawler.politeness import RateLimiter, RobotsCache, origin_of, robots_url_for
from kernel.embeddings import embed
from kernel.errors import UpstreamFailedError
from kernel.fetch import GuardedClient
from kernel.logging import get_logger
from modules.market.public import CrawlIngest, CrawlSourceView, NormalizedPosting

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CrawlOutcome:
    source_id: uuid.UUID
    upserted: int
    expired: int
    error: str | None


async def fetch_source(
    client: GuardedClient,
    source: CrawlSourceView,
    *,
    robots: RobotsCache,
    limiter: RateLimiter,
) -> list[NormalizedPosting]:
    adapter = BY_NAME.get(source.kind)
    if adapter is None:
        raise UpstreamFailedError(f"no adapter for source kind {source.kind!r}")

    origin = origin_of(source.endpoint)
    if not robots.knows(origin):
        try:
            await limiter.wait(source.endpoint)
            response = await client.request("GET", robots_url_for(source.endpoint))
            robots.remember(origin, response.text if response.status_code == 200 else None)
        except UpstreamFailedError:
            robots.remember(origin, None)

    if not robots.allows(source.endpoint):
        raise UpstreamFailedError(
            "robots.txt disallows this endpoint", endpoint=source.endpoint
        )

    await limiter.wait(source.endpoint)
    response = await client.request("GET", source.endpoint)
    if response.status_code >= 400:
        raise UpstreamFailedError(
            f"board returned {response.status_code}", endpoint=source.endpoint
        )

    company_name = source.company_name or "Unknown"
    payload = response.json() if _looks_like_json(response.text) else response.text
    return adapter.parse(payload, company_name=company_name)


async def crawl_all(
    ingest: CrawlIngest,
    *,
    user_agent: str,
    timeout_seconds: float,
    rate_limit_per_second: float,
    embedding_model: str,
) -> list[CrawlOutcome]:
    sources = await ingest.due_sources()
    robots = RobotsCache(user_agent)
    limiter = RateLimiter(per_second=rate_limit_per_second)
    outcomes: list[CrawlOutcome] = []

    async with GuardedClient(
        timeout_seconds=timeout_seconds, user_agent=user_agent
    ) as client:
        for source in sources:
            try:
                postings = await fetch_source(
                    client, source, robots=robots, limiter=limiter
                )
            except UpstreamFailedError as exc:
                # One bad board must not stop the run; the source records why.
                log.warning("crawl.source_failed", source_id=str(source.id), reason=exc.message)
                await ingest.record_crawl(source.id, [], error=exc.message)
                outcomes.append(CrawlOutcome(source.id, 0, 0, exc.message))
                continue

            upserted, expired = await ingest.record_crawl(source.id, postings)
            outcomes.append(CrawlOutcome(source.id, upserted, expired, None))
            log.info(
                "crawl.source_done",
                source_id=str(source.id),
                upserted=upserted,
                expired=expired,
            )

    await embed_new_postings(ingest, embedding_model)
    return outcomes


async def embed_new_postings(ingest: CrawlIngest, model_name: str, batch: int = 200) -> int:
    """Embed postings that have none yet. Platform-paid computation."""
    pending = await ingest.postings_needing_embeddings(model_name, limit=batch)
    if not pending:
        return 0
    vectors = embed([text for _id, text in pending], model_name=model_name)
    await ingest.store_embeddings(
        model_name, {posting_id: vector for (posting_id, _), vector in zip(pending, vectors, strict=True)}
    )
    return len(pending)


def _looks_like_json(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith(("{", "["))
