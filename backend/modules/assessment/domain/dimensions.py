"""Skill dimensions: per user, bounded, and stable over time.

Two rules carry the whole feature:

* **Bounded 5-10.** Fewer hides gaps; more makes the radar unreadable and the
  requirement mapping noisy (domain decision 8).
* **Stable ids.** Progress is shown by comparing assessments, which only works
  if "Reliability" means the same thing in March and in June. Re-assessment
  reuses ids; it may add; merges and renames are recorded as lineage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

MIN_DIMENSIONS = 5
MAX_DIMENSIONS = 10


class LineageKind(StrEnum):
    ADDED = "added"
    RENAMED = "renamed"
    MERGED = "merged"


@dataclass(frozen=True, slots=True)
class DimensionScore:
    dimension_id: str
    name: str
    short_name: str
    score: int
    confidence: float
    read: str
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not 0 <= self.score <= 100:
            raise ValueError(f"score for {self.dimension_id} must be between 0 and 100")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence for {self.dimension_id} must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class LineageEntry:
    kind: LineageKind
    dimension_id: str
    from_ids: tuple[str, ...] = field(default_factory=tuple)
    previous_name: str | None = None


class DimensionCountError(ValueError):
    pass


def assert_within_bounds(dimensions: list[DimensionScore]) -> None:
    count = len(dimensions)
    if count < MIN_DIMENSIONS:
        raise DimensionCountError(
            f"an assessment needs at least {MIN_DIMENSIONS} dimensions, got {count}; "
            "ask follow-up questions rather than inventing thin ones"
        )
    if count > MAX_DIMENSIONS:
        raise DimensionCountError(
            f"an assessment may have at most {MAX_DIMENSIONS} dimensions, got {count}; "
            "merge related dimensions instead"
        )


def assert_ids_unique(dimensions: list[DimensionScore]) -> None:
    ids = [d.dimension_id for d in dimensions]
    if len(set(ids)) != len(ids):
        duplicated = sorted({i for i in ids if ids.count(i) > 1})
        raise ValueError(f"dimension ids must be unique; repeated: {duplicated}")


def derive_lineage(
    previous: dict[str, str], current: list[DimensionScore]
) -> list[LineageEntry]:
    """Work out what changed between two assessments.

    ``previous`` maps dimension id to its name at the time. A reused id whose
    name changed is a rename, not a new dimension — the radar history still
    lines up.
    """
    entries: list[LineageEntry] = []
    for dimension in current:
        if dimension.dimension_id not in previous:
            entries.append(
                LineageEntry(kind=LineageKind.ADDED, dimension_id=dimension.dimension_id)
            )
        elif previous[dimension.dimension_id] != dimension.name:
            entries.append(
                LineageEntry(
                    kind=LineageKind.RENAMED,
                    dimension_id=dimension.dimension_id,
                    previous_name=previous[dimension.dimension_id],
                )
            )
    return entries


def dropped_ids(previous: dict[str, str], current: list[DimensionScore]) -> set[str]:
    """Ids that existed before and are gone now.

    These are recorded as merges so history is never silently orphaned.
    """
    return set(previous) - {d.dimension_id for d in current}


def needs_follow_up(
    dimensions: list[DimensionScore], *, threshold: float
) -> list[DimensionScore]:
    """The domain rule for "the context is not enough".

    A dimension below the confidence threshold is what triggers follow-up
    questions (domain section 2.4).
    """
    return [d for d in dimensions if d.confidence < threshold]
