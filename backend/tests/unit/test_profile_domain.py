"""Evidence citation rules and timeline arithmetic."""

from __future__ import annotations

from datetime import date

import pytest

from domain.profile import (
    CitationError,
    Evidence,
    EvidenceSource,
    Position,
    assert_citations_exist,
    total_experience_months,
)


def test_evidence_confidence_must_be_a_probability() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        Evidence("e1", EvidenceSource.GITHUB, "repo", "fact", date(2026, 1, 1), 1.4)


def test_citing_owned_evidence_is_accepted() -> None:
    assert_citations_exist({"e1", "e2"}, {"e1", "e2", "e3"})


def test_citing_evidence_the_user_does_not_have_is_rejected() -> None:
    """An invented citation is how a fabricated resume claim gets in."""
    with pytest.raises(CitationError) as caught:
        assert_citations_exist({"e1", "made-up"}, {"e1", "e2"})
    assert caught.value.invented == frozenset({"made-up"})


def test_citing_another_users_evidence_is_rejected() -> None:
    with pytest.raises(CitationError):
        assert_citations_exist({"other-users-evidence"}, {"e1"})


def test_citing_nothing_is_allowed() -> None:
    assert_citations_exist(set(), {"e1"})


def test_a_current_position_runs_to_today() -> None:
    position = Position("Engineer", "Kestrel", date(2024, 1, 1), None)
    assert position.is_current
    assert position.months(as_of=date(2026, 1, 1)) == 24


def test_overlapping_positions_are_counted_once() -> None:
    """Two concurrent jobs are not twice the experience."""
    positions = [
        Position("Engineer", "Kestrel", date(2023, 1, 1), date(2025, 1, 1)),
        Position("Advisor", "Sidegig", date(2024, 1, 1), date(2024, 7, 1)),
    ]
    assert total_experience_months(positions, as_of=date(2026, 1, 1)) == 24


def test_adjacent_positions_add_up() -> None:
    positions = [
        Position("Junior", "Kestrel", date(2022, 1, 1), date(2023, 1, 1)),
        Position("Senior", "Northwind", date(2023, 1, 1), date(2024, 1, 1)),
    ]
    assert total_experience_months(positions, as_of=date(2026, 1, 1)) == 24


def test_a_gap_between_positions_is_not_counted() -> None:
    positions = [
        Position("Junior", "Kestrel", date(2022, 1, 1), date(2023, 1, 1)),
        Position("Senior", "Northwind", date(2024, 1, 1), date(2025, 1, 1)),
    ]
    assert total_experience_months(positions, as_of=date(2026, 1, 1)) == 24


def test_no_positions_is_no_experience() -> None:
    assert total_experience_months([], as_of=date(2026, 1, 1)) == 0
