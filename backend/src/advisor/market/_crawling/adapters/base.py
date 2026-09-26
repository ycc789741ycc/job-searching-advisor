"""One adapter per source kind, behind an anti-corruption layer.

Each adapter takes whatever shape a board happens to return and produces
``NormalizedPosting``. Nothing downstream ever sees a vendor's field names.

The crawler may import only ``advisor.market._service`` (plus a few kernel
pieces), which is why the value objects come from there rather than from
``advisor.market._domain``.
"""

from __future__ import annotations

from typing import Any, Protocol

from advisor.market._service import NormalizedPosting, SalaryRange, SourceKind
from kernel.parsing import parse_date, strip_html

__all__ = ["BoardAdapter", "parse_date", "salary_from", "strip_html"]


class BoardAdapter(Protocol):
    name: str
    source_kind: SourceKind

    def endpoint_for(self, slug: str) -> str: ...

    def parse(self, payload: Any, *, company_name: str) -> list[NormalizedPosting]: ...


def salary_from(minimum: Any, maximum: Any, currency: Any) -> SalaryRange | None:
    """Only build a range when the board actually published one."""
    try:
        low = int(float(minimum))
        high = int(float(maximum)) if maximum is not None else low
    except (TypeError, ValueError):
        return None
    if low <= 0:
        return None
    code = str(currency or "").upper()[:3]
    if not code:
        return None
    return SalaryRange(min_amount=low, max_amount=max(low, high), currency=code)
