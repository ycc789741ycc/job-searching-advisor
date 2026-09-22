"""Fit, gaps, and the requirements a person has no evidence for.

Fit is a relationship between a user and a role, never an attribute of the
role. Hiring bar and salary belong to the role; the bubble's size does not
(domain section 2.5).

A role's requirements and a user's dimensions live in different spaces, so the
mapping step is explicit. What a requirement maps to nothing means is the most
important output here.
"""

from __future__ import annotations

from dataclasses import dataclass

# How much an uncovered requirement costs, relative to a dimension scored zero
# against its target. A requirement with no evidence at all is worse than a low
# score, so it is not discounted.
_UNCOVERED_PENALTY = 1.0


@dataclass(frozen=True, slots=True)
class TargetScore:
    dimension_id: str
    target: int

    def __post_init__(self) -> None:
        if not 0 <= self.target <= 100:
            raise ValueError(f"target for {self.dimension_id} must be between 0 and 100")


@dataclass(frozen=True, slots=True)
class SkillGap:
    """The user's score minus the target on one dimension."""

    dimension_id: str
    user_score: int
    target_score: int

    @property
    def delta(self) -> int:
        return self.user_score - self.target_score

    @property
    def is_gap(self) -> bool:
        return self.delta < 0


@dataclass(frozen=True, slots=True)
class UncoveredRequirement:
    """A requirement matching none of the user's dimensions.

    That means no evidence at all, which is different from a low score, and it
    is never dropped silently — otherwise someone with narrow evidence would
    look like a strong fit.
    """

    statement: str
    weight: float


@dataclass(frozen=True, slots=True)
class FitResult:
    score: int
    gaps: tuple[SkillGap, ...]
    uncovered: tuple[UncoveredRequirement, ...]

    @property
    def largest_gaps(self) -> tuple[SkillGap, ...]:
        return tuple(sorted((g for g in self.gaps if g.is_gap), key=lambda g: g.delta))


def evaluate(
    *,
    user_scores: dict[str, int],
    targets: list[TargetScore],
    uncovered: list[UncoveredRequirement],
) -> FitResult:
    """Score one User x Role pair.

    Exceeding a target does not earn credit: being far past the bar on one axis
    does not compensate for being under it on another, which is how interview
    panels actually behave.
    """
    gaps = tuple(
        SkillGap(
            dimension_id=target.dimension_id,
            user_score=user_scores.get(target.dimension_id, 0),
            target_score=target.target,
        )
        for target in targets
    )

    if not gaps and not uncovered:
        return FitResult(score=0, gaps=(), uncovered=())

    shortfall = sum(max(0, -gap.delta) for gap in gaps)
    possible = sum(gap.target_score for gap in gaps)

    # Each uncovered requirement is weighted onto the same 0-100 scale so it
    # actually moves the number rather than being a footnote.
    uncovered_penalty = sum(100 * _UNCOVERED_PENALTY * r.weight for r in uncovered)
    uncovered_possible = sum(100 * r.weight for r in uncovered)

    denominator = possible + uncovered_possible
    if denominator == 0:
        return FitResult(score=100, gaps=gaps, uncovered=tuple(uncovered))

    ratio = (shortfall + uncovered_penalty) / denominator
    score = round(max(0.0, min(1.0, 1.0 - ratio)) * 100)
    return FitResult(score=score, gaps=gaps, uncovered=tuple(uncovered))
