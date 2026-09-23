"""Google sign-in: the attempt cookie, the ID token checks, and the HTTP edge.

Hermetic: Google's keys are a locally generated RSA pair, and the routes run
in-process against a stand-in provider and account service.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import errors
from app.dependencies import REFRESH_COOKIE, get_container
from domain.identity import FederatedSignInRejectedError, IdTokenClaims, SignInFailure
from modules.identity.api import GOOGLE_ATTEMPT_COOKIE, router
from modules.identity.infra.google import (
    ATTEMPT_TTL_SECONDS,
    GoogleEndpoints,
    GoogleOidc,
    PendingSignIn,
    code_challenge,
    new_attempt,
    open_attempt,
    seal_attempt,
)
from modules.identity.public import GoogleSignIn, Session

SECRET = "unit-test-signing-secret-long-enough-to-pass"
CLIENT_ID = "client-123.apps.googleusercontent.test"
WEB = "http://localhost:21471"
ENDPOINTS = GoogleEndpoints(
    authorize_url="https://accounts.google.test/o/oauth2/v2/auth",
    token_url="https://oauth2.google.test/token",
    client_id=CLIENT_ID,
    client_secret="client-secret",
    redirect_uri="http://localhost:21470/api/v1/auth/google/callback",
)

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class StaticKeys:
    def get_key(self, token: str) -> Any:
        return _KEY.public_key()


def _id_token(key: Any = _KEY, **overrides: Any) -> str:
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "google-sub-1",
        "email": "person@example.com",
        "email_verified": True,
        "nonce": "n-1",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm="RS256")


def _oidc() -> GoogleOidc:
    return GoogleOidc(ENDPOINTS, keys=StaticKeys(), timeout_seconds=5, user_agent="test")


# -- the attempt cookie -------------------------------------------------------


def test_an_attempt_round_trips_through_its_cookie() -> None:
    pending = new_attempt()
    opened = open_attempt(seal_attempt(pending, secret=SECRET), state=pending.state, secret=SECRET)
    assert opened == pending


def test_a_verifier_is_long_enough_for_pkce() -> None:
    assert 43 <= len(new_attempt().code_verifier) <= 128


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda p, sealed: (None, p.state), SignInFailure.STATE_MISMATCH),
        (lambda p, sealed: (sealed, "another-state"), SignInFailure.STATE_MISMATCH),
        (lambda p, sealed: ("garbage", p.state), SignInFailure.STATE_MISMATCH),
        (
            lambda p, sealed: (seal_attempt(p, secret="someone-elses-secret"), p.state),
            SignInFailure.STATE_MISMATCH,
        ),
    ],
)
def test_an_answer_this_browser_did_not_start_is_refused(
    mutate: Any, reason: SignInFailure
) -> None:
    """The login-CSRF guard: the state must be the one this browser was given."""
    pending = new_attempt()
    sealed, state = mutate(pending, seal_attempt(pending, secret=SECRET))
    with pytest.raises(FederatedSignInRejectedError) as caught:
        open_attempt(sealed, state=state, secret=SECRET)
    assert caught.value.reason is reason


def test_a_tampered_attempt_does_not_verify() -> None:
    pending = new_attempt()
    _payload, signature = seal_attempt(pending, secret=SECRET).split(".", 1)
    forged = PendingSignIn("s", "n", "v" * 50, pending.started_at)
    forged_payload = seal_attempt(forged, secret="attacker").split(".", 1)[0]
    with pytest.raises(FederatedSignInRejectedError):
        open_attempt(f"{forged_payload}.{signature}", state="s", secret=SECRET)


def test_a_stale_attempt_expires() -> None:
    started = time.time() - ATTEMPT_TTL_SECONDS - 1
    pending = new_attempt(now=started)
    with pytest.raises(FederatedSignInRejectedError) as caught:
        open_attempt(seal_attempt(pending, secret=SECRET), state=pending.state, secret=SECRET)
    assert caught.value.reason is SignInFailure.EXPIRED


# -- where the browser is sent --------------------------------------------------


def test_the_consent_url_carries_state_nonce_and_an_s256_challenge() -> None:
    pending = new_attempt()
    url = urlparse(_oidc().authorize_url(pending))
    params = {key: values[0] for key, values in parse_qs(url.query).items()}

    assert f"{url.scheme}://{url.netloc}{url.path}" == ENDPOINTS.authorize_url
    assert params["client_id"] == CLIENT_ID
    assert params["redirect_uri"] == ENDPOINTS.redirect_uri
    assert params["response_type"] == "code"
    assert params["scope"] == "openid email"
    assert params["state"] == pending.state
    assert params["nonce"] == pending.nonce
    assert params["code_challenge_method"] == "S256"
    assert params["code_challenge"] == code_challenge(pending.code_verifier)
    # The verifier itself never leaves the server.
    assert pending.code_verifier not in url.query


def test_the_challenge_is_rfc_7636_s256() -> None:
    # The worked example from RFC 7636 appendix B.
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert code_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


# -- the ID token -------------------------------------------------------------


def test_a_genuine_id_token_decodes_to_its_claims() -> None:
    claims = _oidc().decode(_id_token())
    assert claims == IdTokenClaims(
        subject="google-sub-1", email="person@example.com", email_verified=True, nonce="n-1"
    )


def test_the_short_issuer_spelling_is_accepted() -> None:
    assert _oidc().decode(_id_token(iss="accounts.google.com")).subject == "google-sub-1"


def test_a_string_true_still_counts_as_verified() -> None:
    assert _oidc().decode(_id_token(email_verified="true")).email_verified


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(lambda: _id_token(key=_OTHER_KEY), id="signed-by-someone-else"),
        pytest.param(lambda: _id_token(aud="another-client"), id="for-another-client"),
        pytest.param(lambda: _id_token(iss="https://evil.test"), id="wrong-issuer"),
        pytest.param(lambda: _id_token(exp=datetime.now(UTC) - timedelta(hours=1)), id="expired"),
    ],
)
def test_a_token_that_does_not_verify_is_refused(token: Any) -> None:
    with pytest.raises(FederatedSignInRejectedError) as caught:
        _oidc().decode(token())
    assert caught.value.reason is SignInFailure.PROVIDER_FAILED


# -- the flow, with a stand-in Google ------------------------------------------


class FakeGoogle:
    def __init__(self) -> None:
        self.claims: IdTokenClaims | None = None
        self.failure: SignInFailure | None = None
        self.codes: list[str] = []

    def authorize_url(self, pending: PendingSignIn) -> str:
        return f"{ENDPOINTS.authorize_url}?state={pending.state}"

    async def claims_for(self, *, code: str, pending: PendingSignIn) -> IdTokenClaims:
        self.codes.append(code)
        if self.failure is not None:
            raise FederatedSignInRejectedError(self.failure, "stand-in failure")
        return self.claims or IdTokenClaims(
            subject="google-sub-1",
            email="person@example.com",
            email_verified=True,
            nonce=pending.nonce,
        )


class FakeAuth:
    def __init__(self) -> None:
        self.signed_in: list[IdTokenClaims] = []

    async def sign_in_with_google(self, claims: IdTokenClaims) -> Session:
        self.signed_in.append(claims)
        now = datetime.now(UTC)
        return Session(
            account_id=uuid.uuid4(),
            email=claims.email,
            access_token="access",
            access_expires_at=now + timedelta(minutes=15),
            refresh_token="refresh-from-google-sign-in",
            refresh_expires_at=now + timedelta(days=30),
        )


def _settings(*, enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        google_sign_in_enabled=enabled,
        oauth_redirect_base_url=WEB,
        auth_cookie_secure=False,
        auth_refresh_token_ttl_days=30,
        auth_access_token_ttl_seconds=900,
    )


@pytest.fixture
def google() -> FakeGoogle:
    return FakeGoogle()


@pytest.fixture
def auth() -> FakeAuth:
    return FakeAuth()


def _client(deps: SimpleNamespace) -> TestClient:
    app = FastAPI()
    errors.install(app)
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_container] = lambda: deps
    return TestClient(app, follow_redirects=False, raise_server_exceptions=False)


@pytest.fixture
def client(google: FakeGoogle, auth: FakeAuth) -> TestClient:
    sign_in = GoogleSignIn(auth, google, secret=SECRET)  # type: ignore[arg-type]
    return _client(SimpleNamespace(settings=_settings(), google_sign_in=sign_in))


def _start(client: TestClient) -> str:
    """Begin an attempt; returns the state Google would send back."""
    response = client.get("/api/v1/auth/google/start")
    assert response.status_code == 302
    return parse_qs(urlparse(response.headers["location"]).query)["state"][0]


def _error_in(response: Any) -> str | None:
    location = urlparse(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}" == WEB
    return parse_qs(location.query).get("sign_in_error", [None])[0]


def test_starting_sets_a_lax_httponly_attempt_cookie_and_goes_to_google(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/auth/google/start")

    assert response.status_code == 302
    assert response.headers["location"].startswith(ENDPOINTS.authorize_url)
    cookie = response.headers["set-cookie"].lower()
    assert f"{GOOGLE_ATTEMPT_COOKIE}=" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/api/v1/auth/google" in cookie


def test_coming_back_signs_in_with_our_own_refresh_cookie(
    client: TestClient, auth: FakeAuth
) -> None:
    state = _start(client)
    response = client.get("/api/v1/auth/google/callback", params={"code": "c", "state": state})

    assert response.status_code == 302
    assert _error_in(response) is None
    assert [claims.email for claims in auth.signed_in] == ["person@example.com"]
    cookies = response.headers.get_list("set-cookie")
    refresh = next(c for c in cookies if c.startswith(f"{REFRESH_COOKIE}="))
    assert "refresh-from-google-sign-in" in refresh
    assert "samesite=strict" in refresh.lower()
    assert "path=/api/v1/auth" in refresh.lower()
    # The attempt is spent either way.
    assert any(c.startswith(f'{GOOGLE_ATTEMPT_COOKIE}=""') for c in cookies)


def test_an_answer_for_another_attempt_signs_nobody_in(
    client: TestClient, auth: FakeAuth, google: FakeGoogle
) -> None:
    _start(client)
    response = client.get(
        "/api/v1/auth/google/callback", params={"code": "c", "state": "not-this-one"}
    )

    assert _error_in(response) == "state_mismatch"
    assert auth.signed_in == []
    # Refused before the code was spent at Google.
    assert google.codes == []


def test_an_answer_without_an_attempt_cookie_is_refused(client: TestClient) -> None:
    response = client.get("/api/v1/auth/google/callback", params={"code": "c", "state": "s"})
    assert _error_in(response) == "state_mismatch"


def test_declining_on_the_consent_screen_says_so(client: TestClient, auth: FakeAuth) -> None:
    _start(client)
    response = client.get("/api/v1/auth/google/callback", params={"error": "access_denied"})
    assert _error_in(response) == "declined"
    assert auth.signed_in == []


def test_a_nonce_from_another_attempt_is_refused(
    client: TestClient, auth: FakeAuth, google: FakeGoogle
) -> None:
    google.claims = IdTokenClaims(
        subject="google-sub-1", email="person@example.com", email_verified=True, nonce="stale"
    )
    state = _start(client)
    response = client.get("/api/v1/auth/google/callback", params={"code": "c", "state": state})
    assert _error_in(response) == "nonce_mismatch"
    assert auth.signed_in == []


def test_an_unverified_google_address_is_refused(
    client: TestClient, auth: FakeAuth, google: FakeGoogle
) -> None:
    state = _start(client)
    google.claims = None

    async def unverified(*, code: str, pending: PendingSignIn) -> IdTokenClaims:
        return IdTokenClaims(
            subject="google-sub-1",
            email="person@example.com",
            email_verified=False,
            nonce=pending.nonce,
        )

    google.claims_for = unverified  # type: ignore[method-assign]
    response = client.get("/api/v1/auth/google/callback", params={"code": "c", "state": state})
    assert _error_in(response) == "unverified_email"
    assert auth.signed_in == []


def test_google_refusing_the_code_is_reported_without_detail(
    client: TestClient, google: FakeGoogle
) -> None:
    google.failure = SignInFailure.PROVIDER_FAILED
    state = _start(client)
    response = client.get("/api/v1/auth/google/callback", params={"code": "c", "state": state})
    assert _error_in(response) == "provider_failed"
    assert "stand-in failure" not in response.headers["location"]


def test_when_google_is_not_configured_nothing_goes_to_google() -> None:
    client = _client(SimpleNamespace(settings=_settings(enabled=False), google_sign_in=None))

    assert client.get("/api/v1/auth/methods").json() == {"password": True, "google": False}
    response = client.get("/api/v1/auth/google/start")
    assert _error_in(response) == "not_configured"


def test_the_sign_in_screen_is_told_google_is_on(client: TestClient) -> None:
    assert client.get("/api/v1/auth/methods").json() == {"password": True, "google": True}
