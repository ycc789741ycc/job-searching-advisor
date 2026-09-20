"""Density-based clustering over posting embeddings.

HDBSCAN is used rather than k-means because the number of roles in a user's
market is not known in advance, and postings that belong to no cluster should
stay unclustered rather than be forced into the nearest one.
"""

from __future__ import annotations

from dataclasses import dataclass

NOISE_LABEL = -1


@dataclass(frozen=True, slots=True)
class ClusterResult:
    """``labels[i]`` is the cluster of ``vectors[i]``; ``NOISE_LABEL`` means none."""

    labels: list[int]

    @property
    def cluster_ids(self) -> list[int]:
        return sorted({label for label in self.labels if label != NOISE_LABEL})

    def members(self, cluster_id: int) -> list[int]:
        return [i for i, label in enumerate(self.labels) if label == cluster_id]


def cluster(vectors: list[list[float]], *, min_cluster_size: int = 3) -> ClusterResult:
    """Group similar postings.

    Below ``min_cluster_size`` postings there is nothing to cluster, so every
    posting is returned as noise and the caller falls back to per-posting
    handling rather than inventing a role from one opening.
    """
    if len(vectors) < min_cluster_size:
        return ClusterResult(labels=[NOISE_LABEL] * len(vectors))

    import numpy as np
    from sklearn.cluster import HDBSCAN

    matrix = np.asarray(vectors, dtype="float32")
    model = HDBSCAN(
        min_cluster_size=min_cluster_size,
        metric="euclidean",  # vectors are L2-normalised, so this ranks as cosine does
        cluster_selection_method="eom",
        copy=True,  # never mutate the caller's matrix
    )
    labels = model.fit_predict(matrix)
    return ClusterResult(labels=[int(label) for label in labels])


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """Similarity of two vectors. Pure, so it is unit-testable without numpy."""
    if len(left) != len(right):
        raise ValueError("vectors must have the same length")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = sum(a * a for a in left) ** 0.5
    right_norm = sum(b * b for b in right) ** 0.5
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)
