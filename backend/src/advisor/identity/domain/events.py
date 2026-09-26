"""What identity tells the rest of the system, as domain facts.

``advisor.identity.infra`` maps each to its outbox name and payload.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ProviderCredentialFailed:
    owner_id: uuid.UUID
    reason: str


@dataclass(frozen=True, slots=True)
class UsageBudgetExceeded:
    owner_id: uuid.UUID
    cap_usd: Decimal
    spent_usd: Decimal
    estimated_usd: Decimal


IdentityEvent = ProviderCredentialFailed | UsageBudgetExceeded
