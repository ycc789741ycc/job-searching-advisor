"""Lever job boards: ``https://api.lever.co/v0/postings/{slug}?mode=json``."""

from __future__ import annotations

from typing import Any

from advisor.market._crawling.adapters.base import parse_date, salary_from, strip_html
from advisor.market._service import NormalizedPosting, SourceKind

BASE = "https://api.lever.co/v0/postings"


class LeverAdapter:
    name = "lever"
    source_kind = SourceKind.ATS_BOARD

    def endpoint_for(self, slug: str) -> str:
        return f"{BASE}/{slug}?mode=json"

    def parse(self, payload: Any, *, company_name: str) -> list[NormalizedPosting]:
        jobs = payload if isinstance(payload, list) else []
        postings: list[NormalizedPosting] = []
        for job in jobs:
            title = str(job.get("text") or "").strip()
            if not title:
                continue
            categories = job.get("categories") or {}
            salary_range = job.get("salaryRange") or {}
            description = job.get("descriptionPlain") or strip_html(job.get("description") or "")
            postings.append(
                NormalizedPosting(
                    external_id=str(job.get("id")),
                    company_name=company_name,
                    title=title,
                    location=categories.get("location"),
                    description=description.strip(),
                    url=str(job.get("hostedUrl") or ""),
                    source_kind=self.source_kind,
                    posted_on=parse_date(job.get("createdAt")),
                    salary=salary_from(
                        salary_range.get("min"),
                        salary_range.get("max"),
                        salary_range.get("currency"),
                    ),
                )
            )
        return postings
