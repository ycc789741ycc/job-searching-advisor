"""Greenhouse job boards.

Public JSON meant for syndication:
``https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true``
"""

from __future__ import annotations

from typing import Any

from advisor.market.crawling.adapters.base import parse_date, salary_from, strip_html
from advisor.market.service import NormalizedPosting, SourceKind

BASE = "https://boards-api.greenhouse.io/v1/boards"


class GreenhouseAdapter:
    name = "greenhouse"
    source_kind = SourceKind.ATS_BOARD

    def endpoint_for(self, slug: str) -> str:
        return f"{BASE}/{slug}/jobs?content=true"

    def parse(self, payload: Any, *, company_name: str) -> list[NormalizedPosting]:
        jobs = (payload or {}).get("jobs") or []
        postings: list[NormalizedPosting] = []
        for job in jobs:
            title = str(job.get("title") or "").strip()
            if not title:
                continue
            pay = job.get("pay_input_ranges") or []
            first = pay[0] if pay else {}
            postings.append(
                NormalizedPosting(
                    external_id=str(job.get("id")),
                    company_name=company_name,
                    title=title,
                    location=(job.get("location") or {}).get("name"),
                    description=strip_html(job.get("content") or ""),
                    url=str(job.get("absolute_url") or ""),
                    source_kind=self.source_kind,
                    posted_on=parse_date(job.get("updated_at") or job.get("first_published")),
                    salary=salary_from(
                        first.get("min_cents", 0) / 100 if first.get("min_cents") else None,
                        first.get("max_cents", 0) / 100 if first.get("max_cents") else None,
                        first.get("currency_type"),
                    ),
                )
            )
        return postings
