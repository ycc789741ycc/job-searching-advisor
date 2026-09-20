"""Keeping a role's identity across re-clustering.

Clusters are recomputed whenever a user's market changes, and a naive rerun
would hand every role a new id — breaking the goals and fits that point at it.
Roles therefore have stable ids and emit lineage (domain section 2.5).

Matching is on the postings a cluster contains, not on its name, because the
name is an AI judgement that can wobble while the underlying group does not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# Below this overlap, two groups of postings are not the same role.
SAME_ROLE_THRESHOLD = 0.5


class RoleChange(StrEnum):
    UNCHANGED = "unchanged"
    ADDED = "added"
    SPLIT = "split"
    MERGED = "merged"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class RoleLineage:
    kind: RoleChange
    role_id: str
    from_role_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Reconciliation:
    """``assignments`` maps each new cluster index to the role id it keeps."""

    assignments: dict[int, str]
    lineage: tuple[RoleLineage, ...]
    retired_role_ids: frozenset[str]


def overlap(left: set[str], right: set[str]) -> float:
    """Jaccard overlap of two sets of posting keys."""
    if not left and not right:
        return 0.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def reconcile(
    *,
    previous: dict[str, set[str]],
    clusters: list[set[str]],
    new_id: object,
) -> Reconciliation:
    """Match freshly computed clusters onto the roles that already exist.

    ``new_id`` is a callable minting an id for a genuinely new role; it is
    injected so this stays pure and testable.
    """
    mint = new_id if callable(new_id) else (lambda: "new")

    # Best previous role for each new cluster, greedily by overlap.
    scored: list[tuple[float, int, str]] = [
        (overlap(cluster, members), index, role_id)
        for index, cluster in enumerate(clusters)
        for role_id, members in previous.items()
        if overlap(cluster, members) >= SAME_ROLE_THRESHOLD
    ]
    scored.sort(reverse=True)

    assignments: dict[int, str] = {}
    claimed: set[str] = set()
    for _score, index, role_id in scored:
        if index in assignments or role_id in claimed:
            continue
        assignments[index] = role_id
        claimed.add(role_id)

    lineage: list[RoleLineage] = []

    # Clusters that matched nothing. A cluster overlapping a role that was
    # already claimed is that role splitting, not a brand-new role.
    for index, cluster in enumerate(clusters):
        if index in assignments:
            continue
        role_id = str(mint())
        assignments[index] = role_id
        parents = tuple(
            sorted(
                previous_id
                for previous_id, members in previous.items()
                if previous_id in claimed and overlap(cluster, members) > 0
            )
        )
        lineage.append(
            RoleLineage(
                kind=RoleChange.SPLIT if parents else RoleChange.ADDED,
                role_id=role_id,
                from_role_ids=parents,
            )
        )

    # A cluster that absorbed more than one previous role is a merge.
    for index, cluster in enumerate(clusters):
        kept = assignments[index]
        absorbed = tuple(
            sorted(
                previous_id
                for previous_id, members in previous.items()
                if previous_id != kept
                and previous_id not in claimed
                and overlap(cluster, members) > 0
            )
        )
        if absorbed:
            lineage.append(
                RoleLineage(kind=RoleChange.MERGED, role_id=kept, from_role_ids=absorbed)
            )
            claimed.update(absorbed)

    retired = frozenset(previous) - claimed - set(assignments.values())
    lineage.extend(
        RoleLineage(kind=RoleChange.RETIRED, role_id=role_id) for role_id in sorted(retired)
    )

    return Reconciliation(
        assignments=assignments,
        lineage=tuple(lineage),
        retired_role_ids=retired,
    )
