"""What the gateway needs from the rest of the system, as protocols.

The kernel knows no domain (import-linter contract ``kernel-knows-no-domain``),
so ``identity`` supplies these at the composition root instead of the gateway
importing it. That also makes the gateway testable against a stub with no
database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ProviderCredential:
    """A user's AI credential, still encrypted.

    The gateway is the only place the key is opened, and only for the duration
    of one call.
    """

    provider: str
    model: str
    base_url: str | None
    encrypted_api_key: str
    owner_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class UsageRecord:
    """One row of the AIUsageLedger."""

    owner_id: uuid.UUID
    task: str
    provider: str
    model: str
    template_version: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal


class CredentialStore(Protocol):
    async def load(self, owner_id: uuid.UUID) -> ProviderCredential: ...

    async def mark_failed(self, owner_id: uuid.UUID, reason: str) -> None:
        """Emit ProviderCredentialFailed and pause this user's background jobs."""
        ...


class BudgetGuard(Protocol):
    async def check(self, owner_id: uuid.UUID, estimated_cost_usd: Decimal) -> None:
        """Raise ``BudgetExceededError`` when this call would breach the cap."""
        ...

    async def record(self, usage: UsageRecord) -> None: ...
