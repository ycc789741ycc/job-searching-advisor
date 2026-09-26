"""Clustering helpers that do not need the model loaded."""

from __future__ import annotations

import pytest

from kernel.embeddings import NOISE_LABEL, ClusterResult, cluster, cosine_similarity


def test_too_few_postings_produce_no_roles() -> None:
    """One opening is not a role. The caller falls back rather than inventing one."""
    result = cluster([[1.0, 0.0], [0.0, 1.0]], min_cluster_size=3)
    assert result.labels == [NOISE_LABEL, NOISE_LABEL]
    assert result.cluster_ids == []


def test_clearly_separated_postings_form_distinct_groups() -> None:
    backend = [[1.0, 0.0, 0.0]] * 4
    frontend = [[0.0, 1.0, 0.0]] * 4
    result = cluster([*backend, *frontend], min_cluster_size=3)
    assert len(result.cluster_ids) == 2
    # sorted() on sets uses subset ordering, which is not total — key on the first member.
    groups = sorted((result.members(c) for c in result.cluster_ids), key=min)
    assert groups == [[0, 1, 2, 3], [4, 5, 6, 7]]


def test_members_are_reported_by_index() -> None:
    result = ClusterResult(labels=[0, NOISE_LABEL, 0, 1])
    assert result.members(0) == [0, 2]
    assert result.members(1) == [3]
    assert result.cluster_ids == [0, 1]


def test_cosine_similarity_of_identical_vectors_is_one() -> None:
    assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_similarity_of_orthogonal_vectors_is_zero() -> None:
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_of_a_zero_vector_is_zero_not_an_error() -> None:
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_cosine_similarity_requires_matching_lengths() -> None:
    with pytest.raises(ValueError, match="same length"):
        cosine_similarity([1.0], [1.0, 2.0])
