"""Ashby job boards.

``https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true``
"""

from __future__ import annotations

from typing import Any

from crawler.adapters.base import parse_date, salary_from, strip_html
from modules.market.public import NormalizedPosting, SourceKind

BASE = "https://api.ashbyhq.com/posting-api/job-board"


class AshbyAdapter:
    name = "ashby"
    source_kind = SourceKind.ATS_BOARD

    def endpoint_for(self, slug: str) -> str:
        return f"{BASE}/{slug}?includeCompensation=true"

    def parse(self, payload: Any, *, company_name: str) -> list[NormalizedPosting]:
        jobs = (payload or {}).get("jobs") or []
        postings: list[NormalizedPosting] = []
        for job in jobs:
            title = str(job.get("title") or "").strip()
            if not title:
                continue
            components = (job.get("compensation") or {}).get("summaryComponents") or []
            pay = next(
                (c for c in components if c.get("compensationType") == "Salary"),
                components[0] if components else {},
            )
            description = job.get("descriptionPlain") or strip_html(
                job.get("descriptionHtml") or ""
            )
            postings.append(
                NormalizedPosting(
                    external_id=str(job.get("id")),
                    company_name=company_name,
                    title=title,
                    location=job.get("location"),
                    description=description.strip(),
                    url=str(job.get("jobUrl") or ""),
                    source_kind=self.source_kind,
                    posted_on=parse_date(job.get("publishedAt")),
                    salary=salary_from(
                        pay.get("minValue"), pay.get("maxValue"), pay.get("currencyCode")
                    ),
                )
            )
        return postings
