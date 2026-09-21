"""Identity HTTP surface.

The credential endpoints are write-only: they set, test, replace and delete,
and a read returns provider, model and the last four characters — never the
key (docs/technical_boundaries.md section 4).
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, EmailStr, Field

from app.dependencies import REFRESH_COOKIE, CurrentUser, Deps, refresh_token_from
from modules.identity.public import SUGGESTED_MODELS, Provider, Session

router = APIRouter(tags=["identity"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class SignInRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class SessionResponse(BaseModel):
    """What the client keeps.

    The access token is returned in the body and held in memory. The refresh
    token is NOT here — it goes back as an httpOnly cookie, so a cross-site
    scripting bug cannot read it.
    """

    account_id: str
    email: str
    access_token: str
    expires_in: int


def _respond_with(session: Session, response: Response, deps: Deps) -> SessionResponse:
    settings = deps.settings
    response.set_cookie(
        REFRESH_COOKIE,
        session.refresh_token,
        httponly=True,
        secure=settings.auth_cookie_secure,
        # Strict: this cookie is only ever used by our own SPA calling our own
        # API, so there is no cross-site flow to accommodate — and that closes
        # the cross-site request forgery question outright.
        samesite="strict",
        path="/api/v1/auth",
        max_age=settings.auth_refresh_token_ttl_days * 24 * 60 * 60,
    )
    return SessionResponse(
        account_id=str(session.account_id),
        email=session.email,
        access_token=session.access_token,
        expires_in=settings.auth_access_token_ttl_seconds,
    )


@router.post("/auth/register", status_code=201)
async def register(body: RegisterRequest, response: Response, deps: Deps) -> SessionResponse:
    """Create an account and sign in.

    The address is not verified — nothing is sent to it yet. That has to be in
    place before any notification feature ships.
    """
    session = await deps.auth.register(email=str(body.email), password=body.password)
    return _respond_with(session, response, deps)


@router.post("/auth/sign-in")
async def sign_in(body: SignInRequest, response: Response, deps: Deps) -> SessionResponse:
    session = await deps.auth.sign_in(email=str(body.email), password=body.password)
    return _respond_with(session, response, deps)


@router.post("/auth/refresh")
async def refresh(
    response: Response,
    deps: Deps,
    token: str | None = Depends(refresh_token_from),
) -> SessionResponse:
    """Exchange the refresh cookie for a new access token.

    The old refresh token is retired in the same step, so a stolen one is
    detectable: presenting a spent token revokes the whole chain.
    """
    from kernel.errors import UnauthenticatedError

    if not token:
        raise UnauthenticatedError("Please sign in again.")
    session = await deps.auth.refresh(refresh_token=token)
    return _respond_with(session, response, deps)


@router.post("/auth/sign-out", status_code=204)
async def sign_out(
    response: Response, deps: Deps, token: str | None = Depends(refresh_token_from)
) -> None:
    """Idempotent, and never an error — signing out must always work."""
    await deps.auth.sign_out(refresh_token=token)
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")


@router.post("/auth/sign-out-everywhere", status_code=204)
async def sign_out_everywhere(response: Response, user: CurrentUser, deps: Deps) -> None:
    """Revokes every session for this account. The control after a scare."""
    await deps.auth.sign_out_everywhere(user)
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")


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
