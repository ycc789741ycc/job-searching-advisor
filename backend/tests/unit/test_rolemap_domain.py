"""Hiring bar blending and role identity across re-clustering."""

from __future__ import annotations

import itertools

import pytest

from domain.rolemap import (
    DEFAULT_ROLE_COUNT,
    MAX_ROLE_COUNT,
    MIN_POSTINGS_FOR_A_ROLE,
    MIN_ROLE_COUNT,
    BarBasis,
    RoleChange,
    RoleCountError,
    blend,
    max_role_count,
    overlap,
    rank_by_fit,
    reconcile,
    validate_role_count,
)

# -- hiring bar -------------------------------------------------------------


def test_with_no_reports_the_bar_is_an_estimate() -> None:
    bar = blend(estimated=62, estimate_confidence=0.4, reported=None, reporter_count=0)
    assert bar.value == 62
    assert bar.basis is BarBasis.ESTIMATED
    assert bar.is_estimate


def test_fewer_than_three_reporters_still_uses_the_estimate() -> None:
    """Below the minimum group size a figure could be traced to one person."""
    bar = blend(estimated=62, estimate_confidence=0.4, reported=90, reporter_count=2)
    assert bar.value == 62
    assert bar.basis is BarBasis.ESTIMATED


def test_three_reporters_start_to_move_the_bar() -> None:
    bar = blend(estimated=60, estimate_confidence=0.4, reported=90, reporter_count=3)
    assert 60 < bar.value < 90
    assert bar.basis is BarBasis.BLENDED


def test_more_reporters_pull_the_bar_further_toward_the_reports() -> None:
    few = blend(estimated=60, estimate_confidence=0.4, reported=90, reporter_count=3)
    many = blend(estimated=60, estimate_confidence=0.4, reported=90, reporter_count=9)
    assert many.value > few.value


def test_a_full_sample_is_reported_not_blended() -> None:
    bar = blend(estimated=60, estimate_confidence=0.4, reported=90, reporter_count=20)
    assert bar.value == 90
    assert bar.basis is BarBasis.REPORTED
    assert not bar.is_estimate


def test_the_bar_stays_on_the_scale() -> None:
    def bar(value: int) -> int:
        return blend(
            estimated=value, estimate_confidence=0.2, reported=None, reporter_count=0
        ).value

    assert bar(180) == 100
    assert bar(-40) == 0


# -- role identity ----------------------------------------------------------


def ids():
    counter = itertools.count(1)
    return lambda: f"new-{next(counter)}"


def test_identical_clusters_keep_their_role_ids() -> None:
    """A re-crawl that changes nothing must not renumber the user's roles."""
    previous = {"srbe": {"a", "b", "c"}, "staff": {"x", "y"}}
    result = reconcile(previous=previous, clusters=[{"a", "b", "c"}, {"x", "y"}], new_id=ids())
    assert result.assignments == {0: "srbe", 1: "staff"}
    assert result.lineage == ()


def test_a_cluster_that_gains_a_posting_is_still_the_same_role() -> None:
    previous = {"srbe": {"a", "b", "c"}}
    result = reconcile(previous=previous, clusters=[{"a", "b", "c", "d"}], new_id=ids())
    assert result.assignments == {0: "srbe"}


def test_a_genuinely_new_group_gets_a_new_id() -> None:
    previous = {"srbe": {"a", "b", "c"}}
    result = reconcile(previous=previous, clusters=[{"a", "b", "c"}, {"p", "q", "r"}], new_id=ids())
    assert result.assignments[0] == "srbe"
    assert result.assignments[1] == "new-1"
    assert [e.kind for e in result.lineage] == [RoleChange.ADDED]


def test_a_role_splitting_is_recorded_with_its_parent() -> None:
    """A goal pointing at the old role must be able to find its successor."""
    previous = {"srbe": {"a", "b", "c", "d"}}
    result = reconcile(previous=previous, clusters=[{"a", "b", "c"}, {"d"}], new_id=ids())
    split = [e for e in result.lineage if e.kind is RoleChange.SPLIT]
    assert len(split) == 1
    assert split[0].from_role_ids == ("srbe",)


def test_two_roles_collapsing_into_one_is_recorded_as_a_merge() -> None:
    previous = {"srbe": {"a", "b", "c"}, "fs": {"d"}}
    result = reconcile(previous=previous, clusters=[{"a", "b", "c", "d"}], new_id=ids())
    merged = [e for e in result.lineage if e.kind is RoleChange.MERGED]
    assert len(merged) == 1
    assert merged[0].role_id == "srbe"
    assert merged[0].from_role_ids == ("fs",)


def test_a_role_whose_postings_all_vanished_is_retired_not_silently_dropped() -> None:
    previous = {"srbe": {"a", "b"}, "gone": {"z"}}
    result = reconcile(previous=previous, clusters=[{"a", "b"}], new_id=ids())
    assert result.retired_role_ids == frozenset({"gone"})
    assert [e.role_id for e in result.lineage if e.kind is RoleChange.RETIRED] == ["gone"]


def test_a_barely_overlapping_cluster_is_not_the_same_role() -> None:
    previous = {"srbe": {"a", "b", "c", "d", "e"}}
    result = reconcile(previous=previous, clusters=[{"a", "z", "y", "x", "w"}], new_id=ids())
    assert result.assignments[0] == "new-1"


def test_the_first_clustering_gives_every_role_a_new_id() -> None:
    result = reconcile(previous={}, clusters=[{"a"}, {"b"}], new_id=ids())
    assert sorted(result.assignments.values()) == ["new-1", "new-2"]
    assert all(e.kind is RoleChange.ADDED for e in result.lineage)


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ({"a"}, {"a"}, 1.0),
        ({"a"}, {"b"}, 0.0),
        ({"a", "b"}, {"b", "c"}, 1 / 3),
        (set(), set(), 0.0),
    ],
)
def test_overlap_is_jaccard(left: set[str], right: set[str], expected: float) -> None:
    assert overlap(left, right) == pytest.approx(expected)


# -- the cost ceiling -------------------------------------------------------


@pytest.mark.parametrize(
    ("postings", "expected"),
    [
        (0, 0),
        (MIN_POSTINGS_FOR_A_ROLE - 1, 0),
        (MIN_POSTINGS_FOR_A_ROLE, 1),
        (10, 3),
        (410, DEFAULT_ROLE_COUNT),
    ],
)
def test_no_more_roles_than_full_clusters_fit_or_than_are_analysed(
    postings: int, expected: int
) -> None:
    assert max_role_count(postings) == expected


def test_a_negative_posting_count_is_a_bug_not_zero_roles() -> None:
    with pytest.raises(ValueError, match="negative"):
        max_role_count(-1)


# -- the user's k -------------------------------------------------------------


def test_the_default_k_sits_inside_the_bound() -> None:
    assert MIN_ROLE_COUNT <= DEFAULT_ROLE_COUNT <= MAX_ROLE_COUNT


@pytest.mark.parametrize("role_count", [MIN_ROLE_COUNT, DEFAULT_ROLE_COUNT, MAX_ROLE_COUNT])
def test_a_k_inside_the_bound_is_accepted(role_count: int) -> None:
    assert validate_role_count(role_count) == role_count


@pytest.mark.parametrize("role_count", [0, MIN_ROLE_COUNT - 1, MAX_ROLE_COUNT + 1, 1000])
def test_a_k_outside_the_bound_is_refused(role_count: int) -> None:
    """An unbounded k would put the cost back in proportion to the market."""
    with pytest.raises(RoleCountError, match="between"):
        validate_role_count(role_count)


@pytest.mark.parametrize(
    ("postings", "role_count", "expected"),
    [
        (410, MIN_ROLE_COUNT, MIN_ROLE_COUNT),
        (410, MAX_ROLE_COUNT, MAX_ROLE_COUNT),
        (10, MAX_ROLE_COUNT, 3),
    ],
)
def test_the_cost_ceiling_follows_the_users_k(
    postings: int, role_count: int, expected: int
) -> None:
    assert max_role_count(postings, role_count) == expected


def test_the_cost_ceiling_refuses_a_k_outside_the_bound() -> None:
    with pytest.raises(RoleCountError):
        max_role_count(410, MAX_ROLE_COUNT + 1)


# -- choosing which clusters are analysed -----------------------------------


def _axis(index: int, weight: float = 1.0) -> list[float]:
    vector = [0.0] * 16
    vector[index] = weight
    return vector


def test_the_clusters_closest_to_the_profile_come_first() -> None:
    profile = [_axis(2, 3.0), _axis(0, 1.0)]
    clusters = [[_axis(0)] * 3, [_axis(1)] * 3, [_axis(2)] * 3]
    assert rank_by_fit(profile, clusters) == [2, 0, 1]


def test_by_default_no_more_than_ten_clusters_are_kept() -> None:
    profile = [_axis(i, float(i)) for i in range(12)]
    clusters = [[_axis(i)] * 3 for i in range(12)]
    assert rank_by_fit(profile, clusters) == list(range(11, 1, -1))
    assert len(rank_by_fit(profile, clusters)) == DEFAULT_ROLE_COUNT


def test_a_smaller_k_keeps_the_closest_clusters_of_the_larger_one() -> None:
    profile = [_axis(i, float(i)) for i in range(12)]
    clusters = [[_axis(i)] * 3 for i in range(12)]
    assert rank_by_fit(profile, clusters, limit=4) == [11, 10, 9, 8]


def test_fewer_clusters_than_the_limit_are_all_kept() -> None:
    clusters = [[_axis(i)] * 3 for i in range(4)]
    assert sorted(rank_by_fit([_axis(0)], clusters)) == [0, 1, 2, 3]


def test_equally_close_clusters_go_larger_first_then_in_order() -> None:
    profile = [_axis(0)]
    clusters = [[_axis(1)] * 3, [_axis(2)] * 5, [_axis(3)] * 3]
    assert rank_by_fit(profile, clusters) == [1, 0, 2]


def test_with_no_profile_the_largest_clusters_are_kept() -> None:
    """A user who has connected nothing yet still gets a map."""
    clusters = [[_axis(i)] * (3 + i) for i in range(12)]
    assert rank_by_fit([], clusters) == list(range(11, 1, -1))


def test_a_profile_in_another_embedding_space_is_a_bug() -> None:
    with pytest.raises(ValueError, match="same length"):
        rank_by_fit([[1.0, 0.0]], [[_axis(0)] * 3])
