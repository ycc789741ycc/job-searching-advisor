"""Salary bands, computed per selected market."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

# Below this many postings a band is shown, but flagged: a role is not hidden
# from a user's map just because their market is thin (domain section 2.5).
CONFIDENT_SAMPLE_SIZE = 5


@dataclass(frozen=True, slots=True)
class SalaryBand:
    low: int
    mid: int
    high: int
    currency: str
    sample_size: int

    @property
    def is_confident(self) -> bool:
        return self.sample_size >= CONFIDENT_SAMPLE_SIZE


def band_from(ranges: list[tuple[int, int, str]]) -> SalaryBand | None:
    """Build one band from the postings in a role that published pay.

    Postings without pay are simply absent from ``ranges`` — they must not drag
    the band toward zero.
    """
    if not ranges:
        return None

    currency = ranges[0][2]
    comparable = [(low, high) for low, high, code in ranges if code == currency]
    if not comparable:
        return None

    lows = sorted(low for low, _ in comparable)
    highs = sorted(high for _, high in comparable)
    midpoints = [(low + high) // 2 for low, high in comparable]

    return SalaryBand(
        low=lows[len(lows) // 4],
        mid=int(median(midpoints)),
        high=highs[(3 * len(highs)) // 4] if len(highs) >= 4 else highs[-1],
        currency=currency,
        sample_size=len(comparable),
    )
