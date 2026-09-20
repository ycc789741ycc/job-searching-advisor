"""The career timeline half of a CareerProfile."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class Position:
    title: str
    company: str
    started_on: date
    ended_on: date | None

    @property
    def is_current(self) -> bool:
        return self.ended_on is None

    def months(self, *, as_of: date) -> int:
        end = self.ended_on or as_of
        return max(0, (end.year - self.started_on.year) * 12 + end.month - self.started_on.month)


def total_experience_months(positions: list[Position], *, as_of: date) -> int:
    """Overlapping positions are counted once.

    Someone who contracted for two companies at the same time has not worked
    twice as long, and a resume that claims so does not survive an interview.
    """
    if not positions:
        return 0

    spans = sorted(
        (p.started_on, p.ended_on or as_of)
        for p in positions
        if (p.ended_on or as_of) >= p.started_on
    )
    merged: list[tuple[date, date]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    return sum((end.year - start.year) * 12 + end.month - start.month for start, end in merged)
