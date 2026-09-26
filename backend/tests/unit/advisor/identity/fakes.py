"""In-memory identity storage: the domain's repository interfaces, with no database."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from advisor.identity.domain import (
    Account,
    AccountFilter,
    AiUsageBudget,
    AiUsageBudgetFilter,
    AiUsageEntry,
    AiUsageEntryFilter,
    FederatedIdentity,
    FederatedIdentityFilter,
    IdentityEvent,
    PasswordCredential,
    PasswordCredentialFilter,
    ProviderCredential,
    ProviderCredentialFilter,
    RefreshToken,
    RefreshTokenFilter,
)
from tests.unit.kernel.db.fake_repository import FakeRepository


@dataclass
class Store:
    accounts: dict[uuid.UUID, Account] = field(default_factory=dict)
    passwords: dict[uuid.UUID, PasswordCredential] = field(default_factory=dict)
    federated: dict[uuid.UUID, FederatedIdentity] = field(default_factory=dict)
    refresh_tokens: dict[uuid.UUID, RefreshToken] = field(default_factory=dict)
    credentials: dict[uuid.UUID, ProviderCredential] = field(default_factory=dict)
    budgets: dict[uuid.UUID, AiUsageBudget] = field(default_factory=dict)
    usage: dict[uuid.UUID, AiUsageEntry] = field(default_factory=dict)
    events: list[IdentityEvent] = field(default_factory=list)


class FakeAccounts(FakeRepository[Account, AccountFilter]):
    noun = "account"

    def matches(self, entity: Account, filter: AccountFilter) -> bool:
        return filter.email is None or entity.email == filter.email


class FakePasswords(FakeRepository[PasswordCredential, PasswordCredentialFilter]):
    owner_field = "account_id"
    noun = "password"

    def matches(self, entity: PasswordCredential, filter: PasswordCredentialFilter) -> bool:
        return filter.account_id is None or entity.account_id == filter.account_id


class FakeFederated(FakeRepository[FederatedIdentity, FederatedIdentityFilter]):
    owner_field = "account_id"
    noun = "linked identity"

    def matches(self, entity: FederatedIdentity, filter: FederatedIdentityFilter) -> bool:
        return (
            (filter.provider is None or entity.provider == filter.provider)
            and (filter.subject is None or entity.subject == filter.subject)
            and (filter.account_id is None or entity.account_id == filter.account_id)
        )


class FakeRefreshTokens(FakeRepository[RefreshToken, RefreshTokenFilter]):
    updated_field = None
    owner_field = "account_id"
    noun = "refresh token"

    def matches(self, entity: RefreshToken, filter: RefreshTokenFilter) -> bool:
        return (
            (filter.token_hash is None or entity.token_hash == filter.token_hash)
            and (filter.family_id is None or entity.family_id == filter.family_id)
            and (filter.account_id is None or entity.account_id == filter.account_id)
            and (filter.is_revoked is None or (entity.revoked_at is not None) == filter.is_revoked)
        )

    async def revoke_all(self, filter: RefreshTokenFilter, *, at: datetime) -> int:
        live = RefreshTokenFilter(
            token_hash=filter.token_hash,
            family_id=filter.family_id,
            account_id=filter.account_id,
            is_revoked=False,
        )
        revoked = 0
        for token in self._visible().values():
            if self.matches(token, live):
                token.revoked_at = at
                revoked += 1
        return revoked


class FakeCredentials(FakeRepository[ProviderCredential, ProviderCredentialFilter]):
    owner_field = "owner_id"
    noun = "AI credential"

    def matches(self, entity: ProviderCredential, filter: ProviderCredentialFilter) -> bool:
        return True


class FakeBudgets(FakeRepository[AiUsageBudget, AiUsageBudgetFilter]):
    owner_field = "owner_id"
    noun = "AI budget"

    def matches(self, entity: AiUsageBudget, filter: AiUsageBudgetFilter) -> bool:
        return True


class FakeUsage(FakeRepository[AiUsageEntry, AiUsageEntryFilter]):
    created_field = "occurred_at"
    updated_field = None
    owner_field = "owner_id"
    noun = "AI usage entry"

    def matches(self, entity: AiUsageEntry, filter: AiUsageEntryFilter) -> bool:
        return filter.occurred_since is None or entity.occurred_at >= filter.occurred_since

    async def total_cost(self, filter: AiUsageEntryFilter) -> Decimal:
        return sum(
            (e.cost_usd for e in self._visible().values() if self.matches(e, filter)),
            Decimal(0),
        )


class FakeAuthentication:
    def __init__(self, store: Store, owner_id: uuid.UUID | None = None) -> None:
        self.accounts = FakeAccounts(store.accounts)
        self.passwords = FakePasswords(store.passwords, owner_id=owner_id)
        self.federated = FakeFederated(store.federated, owner_id=owner_id)
        self.refresh_tokens = FakeRefreshTokens(store.refresh_tokens, owner_id=owner_id)


class FakeOwner(FakeAuthentication):
    def __init__(self, store: Store, owner_id: uuid.UUID) -> None:
        super().__init__(store, owner_id)
        self.credentials = FakeCredentials(store.credentials, owner_id=owner_id)
        self.budgets = FakeBudgets(store.budgets, owner_id=owner_id)
        self.usage = FakeUsage(store.usage, owner_id=owner_id)
        self.pending: list[IdentityEvent] = []

    def record(self, event: IdentityEvent) -> None:
        self.pending.append(event)


class FakeIdentityUnitOfWork:
    def __init__(self, store: Store | None = None) -> None:
        self.store = store or Store()

    @asynccontextmanager
    async def for_owner(self, owner_id: uuid.UUID) -> AsyncIterator[FakeOwner]:
        scope = FakeOwner(self.store, owner_id)
        yield scope
        self.store.events.extend(scope.pending)

    @asynccontextmanager
    async def unauthenticated(self) -> AsyncIterator[FakeAuthentication]:
        yield FakeAuthentication(self.store)
