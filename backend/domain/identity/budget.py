"""Spending rules for background work run on the user's own key.

Scheduled jobs spend the user's money, so a job that would breach the monthly
cap pauses and notifies instead of running (domain section 2.8).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class BudgetState:
    monthly_cap_usd: Decimal
    spent_this_month_usd: Decimal

    @property
    def remaining_usd(self) -> Decimal:
        return max(Decimal(0), self.monthly_cap_usd - self.spent_this_month_usd)

    @property
    def is_exhausted(self) -> bool:
        return self.spent_this_month_usd >= self.monthly_cap_usd

    def would_exceed(self, estimated_cost_usd: Decimal) -> bool:
        """Checked before the call, against an estimate, never after the fact."""
        return self.spent_this_month_usd + estimated_cost_usd > self.monthly_cap_usd


def billing_month_start(today: date) -> date:
    """Budgets reset on the first of the calendar month."""
    return today.replace(day=1)
