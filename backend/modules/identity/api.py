"""Identity HTTP surface.

The credential endpoints are write-only: they set, test, replace and delete,
and a read returns provider, model and the last four characters — never the
key (docs/technical_boundaries.md section 4).
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.dependencies import CurrentUser, Deps
from modules.identity.public import SUGGESTED_MODELS, Provider

router = APIRouter(tags=["identity"])


class CredentialRequest(BaseModel):
    provider: str
    model: str = Field(min_length=1, max_length=128)
    api_key: str = Field(min_length=1)
    base_url: str | None = None


class CredentialResponse(BaseModel):
    provider: str
    model: str
    base_url: str | None
    last_four: str
    status: str
    last_error: str | None


class BudgetRequest(BaseModel):
    monthly_cap_usd: Decimal = Field(ge=0)


@router.get("/me")
async def me(user: CurrentUser, deps: Deps) -> dict[str, object]:
    account = await deps.identity.account(user)
    return {
        "id": str(account.id),
        "email": account.email,
        "background_jobs_paused": account.background_jobs_paused,
        "paused_reason": account.paused_reason,
    }


@router.get("/ai-providers")
async def providers() -> dict[str, list[str]]:
    """What the settings screen offers. A user may type any model they have."""
    return {str(provider): list(models) for provider, models in SUGGESTED_MODELS.items()}


@router.get("/ai-credential")
async def read_credential(user: CurrentUser, deps: Deps) -> CredentialResponse | None:
    credential = await deps.identity.credential(user)
    if credential is None:
        return None
    return CredentialResponse(
        provider=str(credential.provider),
        model=credential.model,
        base_url=credential.base_url,
        last_four=credential.last_four,
        status=str(credential.status),
        last_error=credential.last_error,
    )


@router.put("/ai-credential")
async def set_credential(
    body: CredentialRequest, user: CurrentUser, deps: Deps
) -> CredentialResponse:
    credential = await deps.identity.set_credential(
        user,
        provider=body.provider,
        model=body.model,
        api_key=body.api_key,
        base_url=body.base_url,
    )
    return CredentialResponse(
        provider=str(credential.provider),
        model=credential.model,
        base_url=credential.base_url,
        last_four=credential.last_four,
        status=str(credential.status),
        last_error=credential.last_error,
    )


@router.delete("/ai-credential", status_code=204)
async def delete_credential(user: CurrentUser, deps: Deps) -> None:
    await deps.identity.delete_credential(user)


@router.get("/ai-budget")
async def read_budget(user: CurrentUser, deps: Deps) -> dict[str, str]:
    budget = await deps.identity.budget(user)
    return {
        "monthly_cap_usd": str(budget.monthly_cap_usd),
        "spent_this_month_usd": str(budget.spent_this_month_usd),
        "remaining_usd": str(budget.remaining_usd),
    }


@router.put("/ai-budget")
async def set_budget(body: BudgetRequest, user: CurrentUser, deps: Deps) -> dict[str, str]:
    budget = await deps.identity.set_budget(user, monthly_cap_usd=body.monthly_cap_usd)
    return {
        "monthly_cap_usd": str(budget.monthly_cap_usd),
        "spent_this_month_usd": str(budget.spent_this_month_usd),
        "remaining_usd": str(budget.remaining_usd),
    }


__all__ = ["Provider", "router"]
