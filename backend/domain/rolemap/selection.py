"""Which clusters become roles, and how many there can be.

Every role costs two calls on the user's key, so a role map analyses only the
``MAX_ROLES_ANALYZED`` clusters closest to the user's profile. Closeness is
decided before any AI runs, from local embeddings: the assessed fit needs a
role's requirements, and those come from the very analysis this limits.

The cost shown before a first role map comes from the api, which runs no local
ML (technical boundaries: embeddings and clustering live in the crawler and the
worker). So that estimate is a ceiling rather than a prediction: every cluster
needs at least ``MIN_POSTINGS_FOR_A_ROLE`` members, which bounds how many there
can be, and the user is never charged more than they were shown.
"""

from __future__ import annotations

from collections.abc import Sequence

# Below this, there is nothing to cluster and no role worth naming.
MIN_POSTINGS_FOR_A_ROLE = 3
# The most roles one role map analyses on the user's key (ADR 0002).
MAX_ROLES_ANALYZED = 10

Vector = Sequence[float]


def max_role_count(posting_count: int) -> int:
    """The most roles ``posting_count`` postings can turn into."""
    if posting_count < 0:
        raise ValueError("posting_count cannot be negative")
    return min(posting_count // MIN_POSTINGS_FOR_A_ROLE, MAX_ROLES_ANALYZED)


def rank_by_fit(
    profile: Sequence[Vector],
    clusters: Sequence[Sequence[Vector]],
    *,
    limit: int = MAX_ROLES_ANALYZED,
) -> list[int]:
    """Indices of the ``limit`` clusters closest to the profile, closest first.

    Closeness is the cosine between the profile's centroid and each cluster's.
    With no profile to compare against, the largest clusters win, so a new user
    still gets a map. Ties go to the larger cluster, then the earlier index,
    so the same inputs always select the same roles.
    """
    if limit < 0:
        raise ValueError("limit cannot be negative")
    target = _centroid(profile) if profile else None

    def score(index: int) -> tuple[float, int, int]:
        members = clusters[index]
        closeness = _cosine(target, _centroid(members)) if target and members else 0.0
        return (-closeness, -len(members), index)

    return sorted(range(len(clusters)), key=score)[:limit]


def _centroid(vectors: Sequence[Vector]) -> list[float]:
    dimensions = len(vectors[0])
    if any(len(v) != dimensions for v in vectors):
        raise ValueError("vectors must have the same length")
    return [sum(v[i] for v in vectors) / len(vectors) for i in range(dimensions)]


def _cosine(left: Vector, right: Vector) -> float:
    if len(left) != len(right):
        raise ValueError("vectors must have the same length")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norms = sum(a * a for a in left) ** 0.5 * sum(b * b for b in right) ** 0.5
    return dot / norms if norms else 0.0
