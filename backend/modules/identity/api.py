"""Identity HTTP surface.

Sign-in is our own: email and password, or Google through our own OpenID
Connect exchange. Either way it ends in the same session — an access token in
the body and a rotating refresh token in an httpOnly cookie (ADRs 0001, 0008).

The credential endpoints are write-only: they set, test, replace and delete,
and a read returns provider, model and the last four characters — never the
key (docs/technical_boundaries.md section 4).
"""

from __future__ import annotations

from decimal import Decimal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field

from app.dependencies import REFRESH_COOKIE, CurrentUser, Deps, refresh_token_from
from domain.identity import FederatedSignInRejectedError, SignInFailure
from kernel.config import Settings, must
from kernel.logging import get_logger
from modules.identity.infra.google import ATTEMPT_TTL_SECONDS
from modules.identity.public import SUGGESTED_MODELS, Provider, Session

router = APIRouter(tags=["identity"])
log = get_logger(__name__)

# The one record of a Google sign-in in progress (modules.identity.google).
GOOGLE_ATTEMPT_COOKIE = "jsa_google_attempt"
_GOOGLE_PATH = "/api/v1/auth/google"


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
    _set_refresh_cookie(session, response, settings)
    return SessionResponse(
        account_id=str(session.account_id),
        email=session.email,
        access_token=session.access_token,
        expires_in=settings.auth_access_token_ttl_seconds,
    )


def _set_refresh_cookie(session: Session, response: Response, settings: Settings) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        session.refresh_token,
        httponly=True,
        secure=settings.auth_cookie_secure,
        # Strict: this cookie is only ever *sent* by our own SPA calling our own
        # API, so there is no cross-site flow to accommodate — and that closes
        # the cross-site request forgery question outright. The Google callback
        # sets it on a redirect Google started, but the SPA's refresh is still
        # what sends it (ADR 0008).
        samesite="strict",
        path="/api/v1/auth",
        max_age=settings.auth_refresh_token_ttl_days * 24 * 60 * 60,
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


class SignInMethods(BaseModel):
    password: bool
    google: bool


@router.get("/auth/methods")
async def sign_in_methods(deps: Deps) -> SignInMethods:
    """Which ways in the sign-in screen should offer."""
    return SignInMethods(password=True, google=deps.settings.google_sign_in_enabled)


@router.get("/auth/google/start", include_in_schema=False)
async def google_start(deps: Deps) -> RedirectResponse:
    """Send the browser to Google. A navigation, not an API call."""
    google = deps.google_sign_in
    if google is None:
        return _back_to_app(deps.settings, failure=SignInFailure.NOT_CONFIGURED)

    start = google.begin()
    response = RedirectResponse(start.redirect_url, status_code=302)
    response.set_cookie(
        GOOGLE_ATTEMPT_COOKIE,
        start.sealed_attempt,
        httponly=True,
        secure=deps.settings.auth_cookie_secure,
        # Lax, not Strict: Google sends the browser back with a cross-site GET,
        # and a Strict cookie would not come with it. Lax still keeps it off
        # every cross-site request that is not a top-level navigation.
        samesite="lax",
        path=_GOOGLE_PATH,
        max_age=ATTEMPT_TTL_SECONDS,
    )
    return response


@router.get("/auth/google/callback", include_in_schema=False)
async def google_callback(
    request: Request,
    deps: Deps,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Where Google sends the browser back.

    Success sets our refresh cookie and returns to the app, which picks the
    session up through the refresh it already does on load. Any failure
    returns to the app with a stable reason and nothing else, so no provider
    detail reaches the page.
    """
    settings = deps.settings
    google = deps.google_sign_in
    failure: SignInFailure | None = None
    session: Session | None = None

    if google is None:
        failure = SignInFailure.NOT_CONFIGURED
    elif error:
        failure = (
            SignInFailure.DECLINED if error == "access_denied" else SignInFailure.PROVIDER_FAILED
        )
    elif not code or not state:
        failure = SignInFailure.STATE_MISMATCH
    else:
        try:
            session = await google.complete(
                code=code,
                state=state,
                sealed_attempt=request.cookies.get(GOOGLE_ATTEMPT_COOKIE),
            )
        except FederatedSignInRejectedError as exc:
            failure = exc.reason
            log.warning("auth.google_rejected", reason=str(exc.reason), detail=exc.message)

    response = _back_to_app(settings, failure=failure)
    # One attempt, one answer: whatever happened, it cannot be replayed.
    response.delete_cookie(GOOGLE_ATTEMPT_COOKIE, path=_GOOGLE_PATH)
    if session is not None:
        _set_refresh_cookie(session, response, settings)
    return response


def _back_to_app(settings: Settings, *, failure: SignInFailure | None) -> RedirectResponse:
    base = must(settings.oauth_redirect_base_url, "OAUTH_REDIRECT_BASE_URL").rstrip("/")
    query = f"?{urlencode({'sign_in_error': str(failure)})}" if failure is not None else ""
    return RedirectResponse(f"{base}/{query}", status_code=302)


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
