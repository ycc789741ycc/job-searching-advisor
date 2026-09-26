"""SQLAlchemy implementations of identity's repositories.

The six methods come from ``kernel.db.repository.SqlAlchemyRepository``. The
authentication repositories are bound to an owner only in the owner scope;
before sign-in there is no owner yet, and row-level security is what limits
what the unauthenticated scope can reach.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import ClassVar

from sqlalchemy import func, select, update
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from advisor.identity.domain import (
    Account,
    AccountFilter,
    AiUsageBudget,
    AiUsageBudgetFilter,
    AiUsageEntry,
    AiUsageEntryFilter,
    FederatedIdentity,
    FederatedIdentityFilter,
    PasswordCredential,
    PasswordCredentialFilter,
    ProviderCredential,
    ProviderCredentialFilter,
    RefreshToken,
    RefreshTokenFilter,
)
from advisor.identity.infra import mappers, models
from kernel.db.repository import SqlAlchemyRepository


class SqlAlchemyAccountRepository(SqlAlchemyRepository[Account, models.Account, AccountFilter]):
    model = models.Account
    id_column = models.Account.id
    created_column = models.Account.created_at
    noun = "account"

    def to_entity(self, row: models.Account) -> Account:
        return mappers.account(row)

    def to_row(self, entity: Account) -> models.Account:
        return mappers.account_row(entity)

    def apply(self, row: models.Account, entity: Account) -> None:
        mappers.apply_account(row, entity)

    def id_of(self, entity: Account) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: AccountFilter) -> list[ColumnElement[bool]]:
        if filter.email is None:
            return []
        return [models.Account.email == filter.email]


class SqlAlchemyPasswordCredentialRepository(
    SqlAlchemyRepository[PasswordCredential, models.PasswordCredential, PasswordCredentialFilter]
):
    model = models.PasswordCredential
    id_column = models.PasswordCredential.id
    created_column = models.PasswordCredential.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = (
        models.PasswordCredential.owner_id
    )
    noun = "password"

    def to_entity(self, row: models.PasswordCredential) -> PasswordCredential:
        return mappers.password(row)

    def to_row(self, entity: PasswordCredential) -> models.PasswordCredential:
        return mappers.password_row(entity)

    def apply(self, row: models.PasswordCredential, entity: PasswordCredential) -> None:
        mappers.apply_password(row, entity)

    def id_of(self, entity: PasswordCredential) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: PasswordCredentialFilter) -> list[ColumnElement[bool]]:
        if filter.account_id is None:
            return []
        return [models.PasswordCredential.owner_id == filter.account_id]


class SqlAlchemyFederatedIdentityRepository(
    SqlAlchemyRepository[FederatedIdentity, models.FederatedIdentity, FederatedIdentityFilter]
):
    model = models.FederatedIdentity
    id_column = models.FederatedIdentity.id
    created_column = models.FederatedIdentity.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = (
        models.FederatedIdentity.owner_id
    )
    noun = "linked identity"

    def to_entity(self, row: models.FederatedIdentity) -> FederatedIdentity:
        return mappers.federated(row)

    def to_row(self, entity: FederatedIdentity) -> models.FederatedIdentity:
        return mappers.federated_row(entity)

    def apply(self, row: models.FederatedIdentity, entity: FederatedIdentity) -> None:
        mappers.apply_federated(row, entity)

    def id_of(self, entity: FederatedIdentity) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: FederatedIdentityFilter) -> list[ColumnElement[bool]]:
        identity = models.FederatedIdentity
        found: list[ColumnElement[bool]] = []
        if filter.provider is not None:
            found.append(identity.provider == filter.provider)
        if filter.subject is not None:
            found.append(identity.subject == filter.subject)
        if filter.account_id is not None:
            found.append(identity.owner_id == filter.account_id)
        return found


class SqlAlchemyRefreshTokenRepository(
    SqlAlchemyRepository[RefreshToken, models.RefreshToken, RefreshTokenFilter]
):
    model = models.RefreshToken
    id_column = models.RefreshToken.id
    created_column = models.RefreshToken.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.RefreshToken.owner_id
    noun = "refresh token"

    def to_entity(self, row: models.RefreshToken) -> RefreshToken:
        return mappers.refresh_token(row)

    def to_row(self, entity: RefreshToken) -> models.RefreshToken:
        return mappers.refresh_token_row(entity)

    def apply(self, row: models.RefreshToken, entity: RefreshToken) -> None:
        mappers.apply_refresh_token(row, entity)

    def id_of(self, entity: RefreshToken) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: RefreshTokenFilter) -> list[ColumnElement[bool]]:
        token = models.RefreshToken
        found: list[ColumnElement[bool]] = []
        if filter.token_hash is not None:
            found.append(token.token_hash == filter.token_hash)
        if filter.family_id is not None:
            found.append(token.family_id == filter.family_id)
        if filter.account_id is not None:
            found.append(token.owner_id == filter.account_id)
        if filter.is_revoked is True:
            found.append(token.revoked_at.is_not(None))
        elif filter.is_revoked is False:
            found.append(token.revoked_at.is_(None))
        return found

    async def revoke_all(self, filter: RefreshTokenFilter, *, at: datetime) -> int:
        live = RefreshTokenFilter(
            token_hash=filter.token_hash,
            family_id=filter.family_id,
            account_id=filter.account_id,
            is_revoked=False,
        )
        result = await self._session.execute(
            update(models.RefreshToken)
            .where(*self._owner_conditions(), *self.conditions(live))
            .values(revoked_at=at)
        )
        return int(getattr(result, "rowcount", 0) or 0)


class SqlAlchemyProviderCredentialRepository(
    SqlAlchemyRepository[ProviderCredential, models.ProviderCredential, ProviderCredentialFilter]
):
    model = models.ProviderCredential
    id_column = models.ProviderCredential.id
    created_column = models.ProviderCredential.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = (
        models.ProviderCredential.owner_id
    )
    noun = "AI credential"

    def to_entity(self, row: models.ProviderCredential) -> ProviderCredential:
        return mappers.credential(row)

    def to_row(self, entity: ProviderCredential) -> models.ProviderCredential:
        return mappers.credential_row(entity)

    def apply(self, row: models.ProviderCredential, entity: ProviderCredential) -> None:
        mappers.apply_credential(row, entity)

    def id_of(self, entity: ProviderCredential) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: ProviderCredentialFilter) -> list[ColumnElement[bool]]:
        return []


class SqlAlchemyAiUsageBudgetRepository(
    SqlAlchemyRepository[AiUsageBudget, models.AiUsageBudget, AiUsageBudgetFilter]
):
    model = models.AiUsageBudget
    id_column = models.AiUsageBudget.id
    created_column = models.AiUsageBudget.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.AiUsageBudget.owner_id
    noun = "AI budget"

    def to_entity(self, row: models.AiUsageBudget) -> AiUsageBudget:
        return mappers.budget(row)

    def to_row(self, entity: AiUsageBudget) -> models.AiUsageBudget:
        return mappers.budget_row(entity)

    def apply(self, row: models.AiUsageBudget, entity: AiUsageBudget) -> None:
        mappers.apply_budget(row, entity)

    def id_of(self, entity: AiUsageBudget) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: AiUsageBudgetFilter) -> list[ColumnElement[bool]]:
        return []


class SqlAlchemyAiUsageEntryRepository(
    SqlAlchemyRepository[AiUsageEntry, models.AiUsageLedger, AiUsageEntryFilter]
):
    model = models.AiUsageLedger
    id_column = models.AiUsageLedger.id
    created_column = models.AiUsageLedger.occurred_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.AiUsageLedger.owner_id
    noun = "AI usage entry"

    def to_entity(self, row: models.AiUsageLedger) -> AiUsageEntry:
        return mappers.usage(row)

    def to_row(self, entity: AiUsageEntry) -> models.AiUsageLedger:
        return mappers.usage_row(entity)

    def apply(self, row: models.AiUsageLedger, entity: AiUsageEntry) -> None:
        mappers.apply_usage(row, entity)

    def id_of(self, entity: AiUsageEntry) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: AiUsageEntryFilter) -> list[ColumnElement[bool]]:
        if filter.occurred_since is None:
            return []
        return [models.AiUsageLedger.occurred_at >= filter.occurred_since]

    async def total_cost(self, filter: AiUsageEntryFilter) -> Decimal:
        result = await self._session.execute(
            select(func.coalesce(func.sum(models.AiUsageLedger.cost_usd), 0)).where(
                *self._owner_conditions(), *self.conditions(filter)
            )
        )
        return Decimal(result.scalar_one())
