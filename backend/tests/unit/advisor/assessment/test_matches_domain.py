"""Ranking the openings inside a user's roles. Pure; no infra."""

from __future__ import annotations

import pytest

from advisor.assessment.domain import MAX_MATCHES, MatchCandidate, rank_matches


def candidate(
    posting: str, *, fit: int | None, role: str = "Backend", company: str = "Acme"
) -> MatchCandidate:
    return MatchCandidate(
        posting_id=posting,
        role_id=role,
        role_name=role,
        company_name=company,
        title=posting,
        fit=fit,
    )


def test_the_best_fitting_role_comes_first_and_unscored_roles_last() -> None:
    ranked = rank_matches(
        [
            candidate("a", fit=None),
            candidate("b", fit=62),
            candidate("c", fit=91, role="Platform"),
        ]
    )
    assert [c.posting_id for c in ranked] == ["c", "b", "a"]


def test_ties_are_broken_the_same_way_every_time() -> None:
    same = [
        candidate("z", fit=80, company="Zeta"),
        candidate("y", fit=80, company="alpha"),
        candidate("x", fit=80, company="Alpha", role="Api"),
    ]
    first = rank_matches(same)
    assert [c.posting_id for c in first] == ["x", "y", "z"]
    assert rank_matches(list(reversed(same))) == first


def test_the_list_is_cut_at_the_limit() -> None:
    many = [candidate(str(i), fit=i) for i in range(30)]
    assert [c.fit for c in rank_matches(many, limit=3)] == [29, 28, 27]


@pytest.mark.parametrize("limit", [0, MAX_MATCHES + 1])
def test_a_limit_outside_the_bound_is_refused(limit: int) -> None:
    with pytest.raises(ValueError, match="between"):
        rank_matches([], limit=limit)
