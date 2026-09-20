"""Hiring bar blending and role identity across re-clustering."""

from __future__ import annotations

import itertools

import pytest

from modules.rolemap.domain import BarBasis, RoleChange, blend, overlap, reconcile


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
    assert blend(estimated=180, estimate_confidence=0.2, reported=None, reporter_count=0).value == 100
    assert blend(estimated=-40, estimate_confidence=0.2, reported=None, reporter_count=0).value == 0


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
    result = reconcile(
        previous=previous, clusters=[{"a", "b", "c"}, {"p", "q", "r"}], new_id=ids()
    )
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
    [({"a"}, {"a"}, 1.0), ({"a"}, {"b"}, 0.0), ({"a", "b"}, {"b", "c"}, 1 / 3), (set(), set(), 0.0)],
)
def test_overlap_is_jaccard(left: set[str], right: set[str], expected: float) -> None:
    assert overlap(left, right) == pytest.approx(expected)
