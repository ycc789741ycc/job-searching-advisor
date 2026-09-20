"""Dimension bounds, lineage, and fit arithmetic."""

from __future__ import annotations

import pytest

from modules.assessment.domain import (
    DimensionCountError,
    DimensionScore,
    LineageKind,
    TargetScore,
    UncoveredRequirement,
    assert_ids_unique,
    assert_within_bounds,
    derive_lineage,
    dropped_ids,
    evaluate,
    needs_follow_up,
)


def dim(id_: str, name: str = "Name", score: int = 70, confidence: float = 0.8) -> DimensionScore:
    return DimensionScore(
        dimension_id=id_,
        name=name,
        short_name=name[:10],
        score=score,
        confidence=confidence,
        read="A read.",
        evidence_ids=("e1",),
    )


def dims(count: int) -> list[DimensionScore]:
    return [dim(f"d{i}") for i in range(count)]


# -- bounds -----------------------------------------------------------------


@pytest.mark.parametrize("count", [5, 7, 10])
def test_a_count_within_bounds_is_accepted(count: int) -> None:
    assert_within_bounds(dims(count))


def test_too_few_dimensions_asks_for_questions_rather_than_invention() -> None:
    with pytest.raises(DimensionCountError, match="follow-up questions"):
        assert_within_bounds(dims(4))


def test_too_many_dimensions_asks_for_a_merge() -> None:
    with pytest.raises(DimensionCountError, match="merge related dimensions"):
        assert_within_bounds(dims(11))


def test_duplicate_dimension_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match=r"repeated: \['d1'\]"):
        assert_ids_unique([dim("d1"), dim("d2"), dim("d1")])


def test_a_score_outside_the_scale_is_rejected() -> None:
    with pytest.raises(ValueError, match="between 0 and 100"):
        dim("d1", score=140)


# -- lineage ----------------------------------------------------------------


def test_reusing_an_id_with_the_same_name_is_not_a_change() -> None:
    previous = {"rel": "Testing & Reliability"}
    assert derive_lineage(previous, [dim("rel", "Testing & Reliability")]) == []


def test_a_reused_id_with_a_new_name_is_a_rename_not_a_new_dimension() -> None:
    """Radar history must still line up after a rename."""
    previous = {"rel": "Testing & Reliability"}
    entries = derive_lineage(previous, [dim("rel", "Reliability Engineering")])
    assert len(entries) == 1
    assert entries[0].kind is LineageKind.RENAMED
    assert entries[0].previous_name == "Testing & Reliability"


def test_a_genuinely_new_id_is_recorded_as_added() -> None:
    entries = derive_lineage({"rel": "Reliability"}, [dim("rel", "Reliability"), dim("prod")])
    assert [e.kind for e in entries] == [LineageKind.ADDED]
    assert entries[0].dimension_id == "prod"


def test_an_id_that_disappears_is_reported_so_history_is_not_orphaned() -> None:
    assert dropped_ids({"rel": "Reliability", "old": "Old"}, [dim("rel", "Reliability")]) == {"old"}


# -- follow-up trigger ------------------------------------------------------


def test_low_confidence_dimensions_trigger_follow_up_questions() -> None:
    dimensions = [dim("a", confidence=0.9), dim("b", confidence=0.3), dim("c", confidence=0.55)]
    assert [d.dimension_id for d in needs_follow_up(dimensions, threshold=0.6)] == ["b", "c"]


def test_a_confident_assessment_asks_nothing() -> None:
    assert needs_follow_up([dim("a", confidence=0.9)], threshold=0.6) == []


def test_confidence_exactly_at_the_threshold_is_confident_enough() -> None:
    assert needs_follow_up([dim("a", confidence=0.6)], threshold=0.6) == []


# -- fit --------------------------------------------------------------------


def test_meeting_every_target_is_a_perfect_fit() -> None:
    result = evaluate(
        user_scores={"a": 80, "b": 70},
        targets=[TargetScore("a", 80), TargetScore("b", 70)],
        uncovered=[],
    )
    assert result.score == 100
    assert result.largest_gaps == ()


def test_exceeding_one_target_does_not_pay_for_missing_another() -> None:
    """A panel does not trade a strength off against a miss."""
    balanced = evaluate(
        user_scores={"a": 80, "b": 80},
        targets=[TargetScore("a", 80), TargetScore("b", 80)],
        uncovered=[],
    )
    lopsided = evaluate(
        user_scores={"a": 100, "b": 60},
        targets=[TargetScore("a", 80), TargetScore("b", 80)],
        uncovered=[],
    )
    assert balanced.score > lopsided.score


def test_a_gap_is_reported_with_its_size_and_direction() -> None:
    result = evaluate(user_scores={"lead": 49}, targets=[TargetScore("lead", 88)], uncovered=[])
    gap = result.gaps[0]
    assert gap.delta == -39 and gap.is_gap
    assert result.largest_gaps == (gap,)


def test_a_dimension_the_user_does_not_have_scores_as_zero_not_as_absent() -> None:
    result = evaluate(user_scores={}, targets=[TargetScore("unknown", 80)], uncovered=[])
    assert result.gaps[0].user_score == 0
    assert result.score == 0


def test_an_uncovered_requirement_lowers_fit_rather_than_being_a_footnote() -> None:
    """Someone with narrow evidence must not look like a strong fit."""
    covered = evaluate(user_scores={"a": 80}, targets=[TargetScore("a", 80)], uncovered=[])
    with_hole = evaluate(
        user_scores={"a": 80},
        targets=[TargetScore("a", 80)],
        uncovered=[UncoveredRequirement("Runs a multi-region platform", 1.0)],
    )
    assert covered.score == 100
    assert with_hole.score < covered.score
    assert with_hole.uncovered[0].statement == "Runs a multi-region platform"


def test_a_lightly_weighted_uncovered_requirement_costs_less_than_a_core_one() -> None:
    def fit(weight: float) -> int:
        return evaluate(
            user_scores={"a": 80},
            targets=[TargetScore("a", 80)],
            uncovered=[UncoveredRequirement("x", weight)],
        ).score

    assert fit(0.2) > fit(1.0)


def test_uncovered_requirements_alone_still_produce_a_score() -> None:
    result = evaluate(
        user_scores={},
        targets=[],
        uncovered=[UncoveredRequirement("x", 1.0)],
    )
    assert result.score == 0


def test_a_role_with_nothing_to_compare_is_not_a_fit_of_one_hundred() -> None:
    assert evaluate(user_scores={"a": 80}, targets=[], uncovered=[]).score == 0


def test_a_target_outside_the_scale_is_rejected() -> None:
    with pytest.raises(ValueError, match="between 0 and 100"):
        TargetScore("a", 120)
