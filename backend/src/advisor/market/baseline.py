"""The platform's baseline crawl list (domain decision 15).

Crawled every week whatever users ask for, so a new user's first role map has
postings to group before they watch a single company. Every entry is a public
job-board API meant for syndication — never a site whose terms forbid crawling
(domain decision 6). It is data reviewed like code, not environment
configuration: `make migrate` loads it, and an entry removed here is retired,
never deleted, so the postings it found still have a source to expire them.

Which employers belong here is a product choice. Keep it short: the platform
pays for crawling and clustering every entry, for every user without markets.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BaselineSource:
    kind: str
    company_name: str
    endpoint: str


BASELINE_SOURCES: tuple[BaselineSource, ...] = (
    BaselineSource(
        "greenhouse",
        "GitLab",
        "https://boards-api.greenhouse.io/v1/boards/gitlab/jobs?content=true",
    ),
    BaselineSource(
        "greenhouse",
        "Cloudflare",
        "https://boards-api.greenhouse.io/v1/boards/cloudflare/jobs?content=true",
    ),
    BaselineSource(
        "greenhouse",
        "Datadog",
        "https://boards-api.greenhouse.io/v1/boards/datadog/jobs?content=true",
    ),
    BaselineSource("lever", "Spotify", "https://api.lever.co/v0/postings/spotify?mode=json"),
    BaselineSource(
        "ashby",
        "Linear",
        "https://api.ashbyhq.com/posting-api/job-board/linear?includeCompensation=true",
    ),
    BaselineSource(
        "ashby",
        "Supabase",
        "https://api.ashbyhq.com/posting-api/job-board/supabase?includeCompensation=true",
    ),
)

__all__ = ["BASELINE_SOURCES", "BaselineSource"]
