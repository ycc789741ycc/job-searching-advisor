"""The bubble chart's X axis: how hard the interview is.

Glassdoor was the obvious source and cannot be crawled, so difficulty is built
from first-party data with an AI estimate covering the cold start. The bar
shifts weight from the estimate to real reports as the sample grows
(domain decision 5).

Phase 1 has no InterviewReports yet, so every bar is ``estimated``. The blend
is written now because the storage and the drawing both depend on the basis.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

# Below this many distinct reporters a company+title figure could be traced
# back to one person, so the estimate is used instead.
MIN_REPORTERS = 3

# Reports reach full weight at this sample size.
_FULL_WEIGHT_SAMPLE = 12


class BarBasis(StrEnum):
    ESTIMATED = "estimated"
    BLENDED = "blended"
    REPORTED = "reported"


@dataclass(frozen=True, slots=True)
class HiringBar:
    value: int
    confidence: float
    basis: BarBasis
    sample_size: int

    @property
    def is_estimate(self) -> bool:
        """Estimated bubbles are drawn differently — a dashed outline."""
        return self.basis is BarBasis.ESTIMATED


def blend(
    *,
    estimated: int,
    estimate_confidence: float,
    reported: int | None,
    reporter_count: int,
) -> HiringBar:
    """Shift weight from the estimate to real reports as the sample grows."""
    if reported is None or reporter_count < MIN_REPORTERS:
        return HiringBar(
            value=_clamp(estimated),
            confidence=estimate_confidence,
            basis=BarBasis.ESTIMATED,
            sample_size=reporter_count,
        )

    weight = min(1.0, reporter_count / _FULL_WEIGHT_SAMPLE)
    value = round(reported * weight + estimated * (1 - weight))
    basis = BarBasis.REPORTED if weight >= 1.0 else BarBasis.BLENDED
    confidence = max(estimate_confidence, weight)
    return HiringBar(
        value=_clamp(value),
        confidence=confidence,
        basis=basis,
        sample_size=reporter_count,
    )


def _clamp(value: int) -> int:
    return max(0, min(100, value))
