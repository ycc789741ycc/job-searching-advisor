"""The identity module's only importable surface.

Other modules and the composition root use what is here; nothing reaches into
``domain/`` or ``infra/`` (import-linter contract ``module-public-surface``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from kernel.ai_gateway.ports import ProviderCredential as GatewayCredential
from kernel.ai_gateway.ports import UsageRecord
from kernel.crypto import encrypt, last_four
from kernel.db import Database
from kernel.db.base import utcnow
from kernel.errors import (
    BudgetExceededError,
    CredentialMissingError,
    NotFoundError,
    ValidationError,
)
from kernel.fetch import assert_public_url
from kernel.outbox import EventName, emit
from modules.identity.domain import (
    SUGGESTED_MODELS,
    BudgetState,
    CredentialStatus,
    CredentialView,
    Provider,
    billing_month_start,
    requires_base_url,
)
from modules.identity.infra.models import (
    Account,
    AiUsageBudget,
    AiUsageLedger,
    ProviderCredential,
)
from modules.identity.infra.repository import (
    AccountRepository,
    BudgetRepository,
    CredentialRepository,
)

__all__ = [
    "SUGGESTED_MODELS",
    "AccountView",
    "BudgetView",
    "CredentialView",
    "IdentityService",
    "Provider",
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

    Also implements the gateway's ``CredentialStore`` and ``BudgetGuard``
    ports, which is why the gateway needs no import of this module.
    """

    def __init__(self, database: Database, *, default_monthly_cap_usd: Decimal) -> None:
        self._db = database
        self._default_cap = default_monthly_cap_usd

    # -- accounts -----------------------------------------------------------

    async def ensure_account(self, *, auth_subject: str, email: str | None) -> AccountView:
        """Find or create the local account behind a verified token.

        Runs in the shared session because the account row is what establishes
        the identity that RLS is later keyed on.
        """
        async with self._db.shared() as session:
            repo = AccountRepository(session)
            account = await repo.by_auth_subject(auth_subject)
            if account is None:
                account = Account(auth_subject=auth_subject, email=email)
                repo.add(account)
                await session.flush()
                budget = AiUsageBudget(owner_id=account.id, monthly_cap_usd=self._default_cap)
                BudgetRepository(session).add(budget)
            elif email is not None and account.email != email:
                account.email = email
            return _account_view(account)

    async def account(self, owner_id: uuid.UUID) -> AccountView:
        async with self._db.for_user(owner_id) as session:
            account = await AccountRepository(session).by_id(owner_id)
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

        async with self._db.for_user(owner_id) as session:
            repo = CredentialRepository(session)
            await repo.delete_for_owner(owner_id)
            await session.flush()
            credential = ProviderCredential(
                owner_id=owner_id,
                provider=str(chosen),
                model=model.strip(),
                base_url=base_url,
                encrypted_api_key=encrypt(api_key, context=str(owner_id)),
                last_four=last_four(api_key),
                status=str(CredentialStatus.ACTIVE),
            )
            repo.add(credential)
            # A replaced key is a reason to try the paused work again.
            await AccountRepository(session).resume_background_jobs(owner_id)
            return _credential_view(credential)

    async def credential(self, owner_id: uuid.UUID) -> CredentialView | None:
        """What the client may see. The key itself is never in this answer."""
        async with self._db.for_user(owner_id) as session:
            credential = await CredentialRepository(session).for_owner(owner_id)
            return _credential_view(credential) if credential is not None else None

    async def delete_credential(self, owner_id: uuid.UUID) -> None:
        async with self._db.for_user(owner_id) as session:
            await CredentialRepository(session).delete_for_owner(owner_id)

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
        async with self._db.for_user(owner_id) as session:
            repo = BudgetRepository(session)
            budget = await repo.for_owner(owner_id)
            if budget is None:
                repo.add(AiUsageBudget(owner_id=owner_id, monthly_cap_usd=monthly_cap_usd))
            else:
                budget.monthly_cap_usd = monthly_cap_usd
        return await self.budget(owner_id)

    async def _budget_state(self, owner_id: uuid.UUID, today: date) -> BudgetState:
        async with self._db.for_user(owner_id) as session:
            repo = BudgetRepository(session)
            budget = await repo.for_owner(owner_id)
            cap = budget.monthly_cap_usd if budget is not None else self._default_cap
            spent = await repo.spent_since(owner_id, billing_month_start(today))
            return BudgetState(monthly_cap_usd=cap, spent_this_month_usd=spent)

    # -- kernel.ai_gateway ports -------------------------------------------

    async def load(self, owner_id: uuid.UUID) -> GatewayCredential:
        async with self._db.for_user(owner_id) as session:
            credential = await CredentialRepository(session).for_owner(owner_id)
            if credential is None:
                raise CredentialMissingError(
                    "no AI provider is configured; analysis runs on your own model",
                    owner_id=str(owner_id),
                )
            return GatewayCredential(
                provider=credential.provider,
                model=credential.model,
                base_url=credential.base_url,
                encrypted_api_key=credential.encrypted_api_key,
                owner_id=owner_id,
            )

    async def mark_failed(self, owner_id: uuid.UUID, reason: str) -> None:
        """A revoked, expired or rate-limited key pauses this user's jobs.

        Reports are never left quietly out of date.
        """
        async with self._db.for_user(owner_id) as session:
            credential = await CredentialRepository(session).for_owner(owner_id)
            if credential is not None:
                credential.status = str(CredentialStatus.FAILED)
                credential.last_error = reason
            await AccountRepository(session).pause_background_jobs(owner_id, reason)
            await emit(
                session,
                EventName.PROVIDER_CREDENTIAL_FAILED,
                {"reason": reason},
                owner_id=owner_id,
            )

    async def check(self, owner_id: uuid.UUID, estimated_cost_usd: Decimal) -> None:
        state = await self._budget_state(owner_id, utcnow().date())
        if state.would_exceed(estimated_cost_usd):
            async with self._db.for_user(owner_id) as session:
                await AccountRepository(session).pause_background_jobs(
                    owner_id, "monthly AI budget reached"
                )
                await emit(
                    session,
                    EventName.USAGE_BUDGET_EXCEEDED,
                    {
                        "cap_usd": str(state.monthly_cap_usd),
                        "spent_usd": str(state.spent_this_month_usd),
                        "estimated_usd": str(estimated_cost_usd),
                    },
                    owner_id=owner_id,
                )
            raise BudgetExceededError(
                "this would take you past your monthly AI budget",
                cap_usd=str(state.monthly_cap_usd),
                spent_usd=str(state.spent_this_month_usd),
            )

    async def record(self, usage: UsageRecord) -> None:
        async with self._db.for_user(usage.owner_id) as session:
            BudgetRepository(session).record(
                AiUsageLedger(
                    owner_id=usage.owner_id,
                    account_id=usage.owner_id,
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


def _account_view(account: Account) -> AccountView:
    return AccountView(
        id=account.id,
        email=account.email,
        background_jobs_paused=account.background_jobs_paused_at is not None,
        paused_reason=account.paused_reason,
    )


def _credential_view(credential: ProviderCredential) -> CredentialView:
    return CredentialView(
        provider=Provider(credential.provider),
        model=credential.model,
        base_url=credential.base_url,
        last_four=credential.last_four,
        status=CredentialStatus(credential.status),
        last_error=credential.last_error,
    )
