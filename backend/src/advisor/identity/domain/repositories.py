"""How identity's use cases reach stored data: interfaces in domain terms.

Every repository has the same six methods (ADR 0011) over one frozen filter per
aggregate. Two extra methods cover what the six cannot express:

* ``RefreshTokenRepository.revoke_all`` — a bulk update. Revoking a rotation
  chain must be one statement, so no token in it can slip through between a
  read and a write.
* ``AiUsageEntryRepository.total_cost`` — a SUM over the month's calls.

The unit of work has two scopes:

* ``for_owner`` — one user's data, under row-level security.
* ``unauthenticated`` — the authentication tables, before anyone is signed in.
  Registration, sign-in and refresh must find an account by address or token
  before there is an ``app.user_id``; the policies on those four tables allow
  exactly that, and nothing else is reachable here.
"""

from __future__ import annotations

import uuid
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from advisor.identity.domain.entities import (
    Account,
    AiUsageBudget,
    AiUsageEntry,
    FederatedIdentity,
    PasswordCredential,
    ProviderCredential,
    RefreshToken,
)
from advisor.identity.domain.events import IdentityEvent


class Repository[Entity, Filter](Protocol):
    """The six methods, as every identity repository has them."""

    async def create(self, entity: Entity) -> Entity: ...

    async def get(self, entity_id: uuid.UUID) -> Entity | None: ...

    async def get_list(
        self, filter: Filter, page: int = 1, page_size: int | None = None
    ) -> list[Entity]: ...

    async def get_count(self, filter: Filter) -> int: ...

    async def update(self, entity: Entity) -> Entity: ...

    async def delete(self, entity_id: uuid.UUID) -> None: ...


@dataclass(frozen=True, slots=True)
class AccountFilter:
    email: str | None = None


class AccountRepository(Repository[Account, AccountFilter], Protocol): ...


@dataclass(frozen=True, slots=True)
class PasswordCredentialFilter:
    account_id: uuid.UUID | None = None


class PasswordCredentialRepository(
    Repository[PasswordCredential, PasswordCredentialFilter], Protocol
): ...


@dataclass(frozen=True, slots=True)
class FederatedIdentityFilter:
    provider: str | None = None
    subject: str | None = None
    account_id: uuid.UUID | None = None


class FederatedIdentityRepository(
    Repository[FederatedIdentity, FederatedIdentityFilter], Protocol
): ...


@dataclass(frozen=True, slots=True)
class RefreshTokenFilter:
    token_hash: str | None = None
    family_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    is_revoked: bool | None = None


class RefreshTokenRepository(Repository[RefreshToken, RefreshTokenFilter], Protocol):
    async def revoke_all(self, filter: RefreshTokenFilter, *, at: datetime) -> int:
        """Revoke every matching token that is still live, in one statement.
        Returns how many."""
        ...


@dataclass(frozen=True, slots=True)
class ProviderCredentialFilter:
    """One credential per user; the owner scope is the only filter."""


class ProviderCredentialRepository(
    Repository[ProviderCredential, ProviderCredentialFilter], Protocol
): ...


@dataclass(frozen=True, slots=True)
class AiUsageBudgetFilter:
    """One budget per user; the owner scope is the only filter."""


class AiUsageBudgetRepository(Repository[AiUsageBudget, AiUsageBudgetFilter], Protocol): ...


@dataclass(frozen=True, slots=True)
class AiUsageEntryFilter:
    occurred_since: datetime | None = None


class AiUsageEntryRepository(Repository[AiUsageEntry, AiUsageEntryFilter], Protocol):
    async def total_cost(self, filter: AiUsageEntryFilter) -> Decimal:
        """What the matching calls cost together; zero when there are none."""
        ...


class Authentication(Protocol):
    """The authentication tables, reachable before anyone is signed in."""

    @property
    def accounts(self) -> AccountRepository: ...

    @property
    def passwords(self) -> PasswordCredentialRepository: ...

    @property
    def federated(self) -> FederatedIdentityRepository: ...

    @property
    def refresh_tokens(self) -> RefreshTokenRepository: ...


class OwnerIdentity(Authentication, Protocol):
    """One user's identity data, under row-level security."""

    @property
    def credentials(self) -> ProviderCredentialRepository: ...

    @property
    def budgets(self) -> AiUsageBudgetRepository: ...

    @property
    def usage(self) -> AiUsageEntryRepository: ...

    def record(self, event: IdentityEvent) -> None: ...


class IdentityUnitOfWork(Protocol):
    def for_owner(self, owner_id: uuid.UUID) -> AbstractAsyncContextManager[OwnerIdentity]: ...

    def unauthenticated(self) -> AbstractAsyncContextManager[Authentication]: ...
