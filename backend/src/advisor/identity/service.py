"""Accounts, the AI credential and the usage budget.

Other components and the composition root reach this only through
``advisor.identity`` (import-linter contract ``identity-public-surface``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from advisor.identity.auth import AuthService, Session
from advisor.identity.domain import (
    SUGGESTED_MODELS,
    Account,
    AiUsageBudget,
    AiUsageBudgetFilter,
    AiUsageEntry,
    AiUsageEntryFilter,
    BudgetState,
    CredentialView,
    IdentityUnitOfWork,
    OwnerIdentity,
    Provider,
    ProviderCredential,
    ProviderCredentialFailed,
    ProviderCredentialFilter,
    UsageBudgetExceeded,
    billing_month_start,
    requires_base_url,
)
from advisor.identity.google import GoogleSignIn, GoogleStart
from advisor.identity.infra.google import GoogleEndpoints, GoogleOidc
from kernel.ai_gateway.ports import ProviderCredential as GatewayCredential
from kernel.ai_gateway.ports import UsageRecord
from kernel.clock import utcnow
from kernel.crypto import encrypt, last_four
from kernel.errors import (
    BudgetExceededError,
    CredentialMissingError,
    NotFoundError,
    ValidationError,
)
from kernel.fetch import assert_public_url

__all__ = [
    "SUGGESTED_MODELS",
    "AccountView",
    "AuthService",
    "BudgetView",
    "CredentialView",
    "GoogleEndpoints",
    "GoogleOidc",
    "GoogleSignIn",
    "GoogleStart",
    "IdentityService",
    "Provider",
    "Session",
]


@dataclass(frozen=True, slots=True)
class AccountView:
    id: uuid.UUID
    email: str | None
    background_jobs_paused: bool
    paused_reason: str | None


@dataclass(frozen=True, slots=True)
class BudgetView:
    monthly_cap_usd: Decimal
    spent_this_month_usd: Decimal
    remaining_usd: Decimal


class IdentityService:
    """Accounts, the AI credential, and the budget that guards it.

    Registration and sign-in live in ``AuthService``, also exported here.

    Also implements the gateway's ``CredentialStore`` and ``BudgetGuard``
    ports, which is why the gateway needs no import of this module.
    """

    def __init__(self, uow: IdentityUnitOfWork, *, default_monthly_cap_usd: Decimal) -> None:
        self._uow = uow
        self._default_cap = default_monthly_cap_usd

    # -- accounts -----------------------------------------------------------

    async def account(self, owner_id: uuid.UUID) -> AccountView:
        async with self._uow.for_owner(owner_id) as mine:
            account = await mine.accounts.get(owner_id)
        if account is None:
            raise NotFoundError("account not found", owner_id=str(owner_id))
        return _account_view(account)

    # -- credential (write-only) -------------------------------------------

    async def set_credential(
        self,
        owner_id: uuid.UUID,
        *,
        provider: str,
        model: str,
        api_key: str,
        base_url: str | None,
    ) -> CredentialView:
        try:
            chosen = Provider(provider)
        except ValueError as exc:
            raise ValidationError(f"unknown provider {provider!r}", provider=provider) from exc

        if not api_key.strip():
            raise ValidationError("an API key is required")
        if not model.strip():
            raise ValidationError("a model is required")

        if requires_base_url(chosen) and not base_url:
            raise ValidationError(
                "a self-hosted model needs a base URL you control", provider=provider
            )
        if base_url:
            # The same SSRF guard the gateway will apply, surfaced at save time
            # so the user is told immediately rather than at the first job.
            assert_public_url(base_url)

        async with self._uow.for_owner(owner_id) as mine:
            await _delete_credential(mine)
            credential = await mine.credentials.create(
                ProviderCredential.configured(
                    owner_id,
                    provider=chosen,
                    model=model.strip(),
                    base_url=base_url,
                    encrypted_api_key=encrypt(api_key, context=str(owner_id)),
                    last_four=last_four(api_key),
                )
            )
            # A replaced key is a reason to try the paused work again.
            account = await mine.accounts.get(owner_id)
            if account is not None:
                account.resume_background_jobs()
                await mine.accounts.update(account)
            return _credential_view(credential)

    async def credential(self, owner_id: uuid.UUID) -> CredentialView | None:
        """What the client may see. The key itself is never in this answer."""
        async with self._uow.for_owner(owner_id) as mine:
            credential = await _credential(mine)
        return _credential_view(credential) if credential is not None else None

    async def delete_credential(self, owner_id: uuid.UUID) -> None:
        async with self._uow.for_owner(owner_id) as mine:
            await _delete_credential(mine)

    # -- budget -------------------------------------------------------------

    async def budget(self, owner_id: uuid.UUID, *, today: date | None = None) -> BudgetView:
        state = await self._budget_state(owner_id, today or utcnow().date())
        return BudgetView(
            monthly_cap_usd=state.monthly_cap_usd,
            spent_this_month_usd=state.spent_this_month_usd,
            remaining_usd=state.remaining_usd,
        )

    async def set_budget(self, owner_id: uuid.UUID, *, monthly_cap_usd: Decimal) -> BudgetView:
        if monthly_cap_usd < 0:
            raise ValidationError("a monthly cap cannot be negative")
        async with self._uow.for_owner(owner_id) as mine:
            budget = await _budget(mine)
            if budget is None:
                await mine.budgets.create(AiUsageBudget.capped(owner_id, monthly_cap_usd))
            else:
                budget.monthly_cap_usd = monthly_cap_usd
                await mine.budgets.update(budget)
        return await self.budget(owner_id)

    async def _budget_state(self, owner_id: uuid.UUID, today: date) -> BudgetState:
        month = billing_month_start(today)
        async with self._uow.for_owner(owner_id) as mine:
            budget = await _budget(mine)
            spent = await mine.usage.total_cost(
                AiUsageEntryFilter(
                    occurred_since=datetime(month.year, month.month, month.day, tzinfo=UTC)
                )
            )
        cap = budget.monthly_cap_usd if budget is not None else self._default_cap
        return BudgetState(monthly_cap_usd=cap, spent_this_month_usd=spent)

    # -- kernel.ai_gateway ports -------------------------------------------

    async def load(self, owner_id: uuid.UUID) -> GatewayCredential:
        async with self._uow.for_owner(owner_id) as mine:
            credential = await _credential(mine)
        if credential is None:
            raise CredentialMissingError(
                "no AI provider is configured; analysis runs on your own model",
                owner_id=str(owner_id),
            )
        return GatewayCredential(
            provider=str(credential.provider),
            model=credential.model,
            base_url=credential.base_url,
            encrypted_api_key=credential.encrypted_api_key,
            owner_id=owner_id,
        )

    async def mark_failed(self, owner_id: uuid.UUID, reason: str) -> None:
        """A revoked, expired or rate-limited key pauses this user's jobs.

        Reports are never left quietly out of date.
        """
        async with self._uow.for_owner(owner_id) as mine:
            credential = await _credential(mine)
            if credential is not None:
                credential.failed(reason)
                await mine.credentials.update(credential)
            await _pause(mine, owner_id, reason)
            mine.record(ProviderCredentialFailed(owner_id=owner_id, reason=reason))

    async def check(self, owner_id: uuid.UUID, estimated_cost_usd: Decimal) -> None:
        state = await self._budget_state(owner_id, utcnow().date())
        if state.would_exceed(estimated_cost_usd):
            async with self._uow.for_owner(owner_id) as mine:
                await _pause(mine, owner_id, "monthly AI budget reached")
                mine.record(
                    UsageBudgetExceeded(
                        owner_id=owner_id,
                        cap_usd=state.monthly_cap_usd,
                        spent_usd=state.spent_this_month_usd,
                        estimated_usd=estimated_cost_usd,
                    )
                )
            raise BudgetExceededError(
                "this would take you past your monthly AI budget",
                cap_usd=str(state.monthly_cap_usd),
                spent_usd=str(state.spent_this_month_usd),
            )

    async def record(self, usage: UsageRecord) -> None:
        async with self._uow.for_owner(usage.owner_id) as mine:
            await mine.usage.create(
                AiUsageEntry(
                    id=uuid.uuid4(),
                    owner_id=usage.owner_id,
                    task=usage.task,
                    provider=usage.provider,
                    model=usage.model,
                    template_version=usage.template_version,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cost_usd=usage.cost_usd,
                    occurred_at=utcnow(),
                )
            )


async def _credential(mine: OwnerIdentity) -> ProviderCredential | None:
    found = await mine.credentials.get_list(ProviderCredentialFilter(), page_size=1)
    return found[0] if found else None


async def _delete_credential(mine: OwnerIdentity) -> None:
    for credential in await mine.credentials.get_list(ProviderCredentialFilter()):
        await mine.credentials.delete(credential.id)


async def _budget(mine: OwnerIdentity) -> AiUsageBudget | None:
    found = await mine.budgets.get_list(AiUsageBudgetFilter(), page_size=1)
    return found[0] if found else None


async def _pause(mine: OwnerIdentity, owner_id: uuid.UUID, reason: str) -> None:
    account = await mine.accounts.get(owner_id)
    if account is not None:
        account.pause_background_jobs(reason, at=utcnow())
        await mine.accounts.update(account)


def _account_view(account: Account) -> AccountView:
    return AccountView(
        id=account.id,
        email=account.email,
        background_jobs_paused=account.background_jobs_paused_at is not None,
        paused_reason=account.paused_reason,
    )


def _credential_view(credential: ProviderCredential) -> CredentialView:
    return CredentialView(
        provider=credential.provider,
        model=credential.model,
        base_url=credential.base_url,
        last_four=credential.last_four,
        status=credential.status,
        last_error=credential.last_error,
    )
