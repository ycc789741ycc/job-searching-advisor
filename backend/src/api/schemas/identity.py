"""Identity's wire shapes: sign-in, the account, the AI credential and budget,
and which key AI runs on."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import EmailStr, Field

from advisor.identity import AccountView, AiSourceView, BudgetView, CredentialView
from api.schemas.common import ApiModel, RequestModel


class RegisterRequest(RequestModel):
    email: EmailStr
    password: str = Field(min_length=1)


class SignInRequest(RequestModel):
    email: EmailStr
    password: str = Field(min_length=1)


class SessionResponse(ApiModel):
    """What the client keeps.

    The access token is returned in the body and held in memory. The refresh
    token is NOT here — it goes back as an httpOnly cookie, so a cross-site
    scripting bug cannot read it.
    """

    account_id: str
    email: str
    access_token: str
    expires_in: int


class SignInMethods(ApiModel):
    password: bool
    google: bool
    # Whether an account signed in with Google starts on CareerPolaris AI
    # (ADR 0066). Never true without Google: the platform needs its identity.
    platform_ai: bool


class Me(ApiModel):
    id: str
    email: str | None
    background_jobs_paused: bool
    paused_reason: str | None

    @classmethod
    def from_view(cls, account: AccountView) -> Me:
        return cls(
            id=str(account.id),
            email=account.email,
            background_jobs_paused=account.background_jobs_paused,
            paused_reason=account.paused_reason,
        )


class CredentialRequest(RequestModel):
    provider: str
    model: str = Field(min_length=1, max_length=128)
    api_key: str = Field(min_length=1)
    base_url: str | None = None


class Credential(ApiModel):
    """Write-only in effect: provider, model and the last four, never the key."""

    provider: str
    model: str
    base_url: str | None
    last_four: str
    status: str
    last_error: str | None

    @classmethod
    def from_view(cls, credential: CredentialView) -> Credential:
        return cls(
            provider=str(credential.provider),
            model=credential.model,
            base_url=credential.base_url,
            last_four=credential.last_four,
            status=str(credential.status),
            last_error=credential.last_error,
        )


class AiSourceRequest(RequestModel):
    source: Literal["own", "platform"]


class PlatformQuota(ApiModel):
    """This account's month on the platform's key. Decimal strings."""

    allowed_usd: str
    spent_usd: str
    remaining_usd: str


class AiSourceBody(ApiModel):
    """Which key AI runs on, and what the user may choose between."""

    source: Literal["own", "platform"] | None
    has_credential: bool
    is_platform_on: bool
    is_eligible: bool
    # None while the platform's key is off.
    platform_quota: PlatformQuota | None

    @classmethod
    def from_view(cls, view: AiSourceView, quota: PlatformQuota | None) -> AiSourceBody:
        return cls(
            source=None if view.source is None else view.source.value,
            has_credential=view.has_credential,
            is_platform_on=view.is_platform_on,
            is_eligible=view.is_eligible,
            platform_quota=quota,
        )


class BudgetRequest(RequestModel):
    monthly_cap_usd: Decimal = Field(ge=0)


class Budget(ApiModel):
    # Decimal strings: money never goes through a float.
    monthly_cap_usd: str
    spent_this_month_usd: str
    remaining_usd: str

    @classmethod
    def from_view(cls, budget: BudgetView) -> Budget:
        return cls(
            monthly_cap_usd=str(budget.monthly_cap_usd),
            spent_this_month_usd=str(budget.spent_this_month_usd),
            remaining_usd=str(budget.remaining_usd),
        )
