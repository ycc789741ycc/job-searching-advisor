"""Career pages carrying schema.org ``JobPosting`` markup.

Companies publish this so search engines index their jobs, which makes it
structured data meant to be read — not scraping around a block.
"""

from __future__ import annotations

import json
import re
from typing import Any

from advisor.market.crawling.adapters.base import parse_date, salary_from, strip_html
from advisor.market.service import NormalizedPosting, SourceKind

_SCRIPT = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def _walk(node: Any) -> list[dict[str, Any]]:
    """JSON-LD nests: a single object, a list, or an @graph."""
    found: list[dict[str, Any]] = []
    if isinstance(node, list):
        for item in node:
            found.extend(_walk(item))
    elif isinstance(node, dict):
        types = node.get("@type")
        types = types if isinstance(types, list) else [types]
        if "JobPosting" in types:
            found.append(node)
        for key in ("@graph", "itemListElement", "item"):
            if key in node:
                found.extend(_walk(node[key]))
    return found


class JsonLdAdapter:
    name = "json-ld"
    source_kind = SourceKind.JSON_LD

    def endpoint_for(self, slug: str) -> str:
        return slug  # the career page URL itself

    def parse(self, payload: Any, *, company_name: str) -> list[NormalizedPosting]:
        blocks: list[dict[str, Any]] = []
        for raw in _SCRIPT.findall(str(payload or "")):
            try:
                blocks.extend(_walk(json.loads(raw)))
            except ValueError:
                continue  # one malformed block must not lose the page

        postings: list[NormalizedPosting] = []
        for job in blocks:
            title = str(job.get("title") or "").strip()
            if not title:
                continue
            employer = job.get("hiringOrganization") or {}
            name = str(employer.get("name") or company_name).strip() or company_name
            salary_spec = (job.get("baseSalary") or {}).get("value") or {}
            postings.append(
                NormalizedPosting(
                    external_id=str(job.get("identifier") or job.get("url") or title),
                    company_name=name,
                    title=title,
                    location=_location(job),
                    description=strip_html(str(job.get("description") or "")),
                    url=str(job.get("url") or ""),
                    source_kind=self.source_kind,
                    posted_on=parse_date(job.get("datePosted")),
                    salary=salary_from(
                        salary_spec.get("minValue"),
                        salary_spec.get("maxValue") or salary_spec.get("value"),
                        (job.get("baseSalary") or {}).get("currency"),
                    ),
                )
            )
        return postings


def _location(job: dict[str, Any]) -> str | None:
    place = job.get("jobLocation")
    place = place[0] if isinstance(place, list) and place else place
    if not isinstance(place, dict):
        return None
    address = place.get("address") or {}
    if not isinstance(address, dict):
        return None
    parts = [address.get("addressLocality"), address.get("addressRegion")]
    joined = ", ".join(str(p) for p in parts if p)
    return joined or (str(address.get("addressCountry")) if address.get("addressCountry") else None)
