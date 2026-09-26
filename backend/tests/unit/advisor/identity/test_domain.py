"""Budget and credential rules. Pure domain — no database, no gateway."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from advisor.identity.domain import BudgetState, Provider, billing_month_start, requires_base_url


def state(cap: str, spent: str) -> BudgetState:
    return BudgetState(monthly_cap_usd=Decimal(cap), spent_this_month_usd=Decimal(spent))


def test_remaining_is_cap_minus_spend() -> None:
    assert state("20", "5.50").remaining_usd == Decimal("14.50")


def test_remaining_never_goes_negative() -> None:
    """Overspend is possible — a call costs more than its estimate — but the
    number shown to the user is floored at zero rather than going red."""
    assert state("20", "25").remaining_usd == Decimal(0)


def test_a_call_within_the_cap_is_allowed() -> None:
    assert not state("20", "5").would_exceed(Decimal("3"))


def test_a_call_that_would_breach_the_cap_is_refused() -> None:
    assert state("20", "18").would_exceed(Decimal("3"))


def test_a_call_landing_exactly_on_the_cap_is_allowed() -> None:
    assert not state("20", "17").would_exceed(Decimal("3"))


def test_exhaustion_is_reported_at_the_cap() -> None:
    assert state("20", "20").is_exhausted
    assert not state("20", "19.99").is_exhausted


@pytest.mark.parametrize(
    ("today", "expected"),
    [(date(2026, 9, 21), date(2026, 9, 1)), (date(2026, 1, 1), date(2026, 1, 1))],
)
def test_budgets_reset_on_the_first_of_the_month(today: date, expected: date) -> None:
    assert billing_month_start(today) == expected


def test_only_a_self_hosted_model_needs_a_base_url() -> None:
    assert requires_base_url(Provider.LOCAL)
    assert not requires_base_url(Provider.ANTHROPIC)
    assert not requires_base_url(Provider.OPENAI)
