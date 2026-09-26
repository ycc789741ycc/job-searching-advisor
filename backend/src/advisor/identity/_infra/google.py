"""Google sign-in: the OpenID Connect authorization-code exchange.

Login OAuth, which is separate from connector OAuth in every way. It uses
another provider, other tokens and other storage, and it shares no code path
with ``advisor.profile._infra.oauth`` (docs/technical_boundaries.md section 4).

The browser is sent to Google with three one-time values: ``state``, ``nonce``
and a PKCE ``code_verifier``. They travel in a signed, short-lived cookie. It
is httpOnly and scoped to the callback path, so no server-side table holds an
attempt that is never finished. On the way back:

* ``state`` must match the cookie, which means this browser started the attempt.
  That stops someone logging a victim in to the attacker's account.
* the code is exchanged with the verifier, so an intercepted code is useless.
* the ID token's signature is checked against Google's published keys, as are
  its issuer, audience and expiry. The nonce and the verified address are
  domain rules (``advisor.identity._domain.federated``).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

import jwt

from advisor.identity._domain import FederatedSignInRejectedError, IdTokenClaims, SignInFailure
from kernel.auth import SigningKeyResolver
from kernel.errors import DomainError
from kernel.fetch import GuardedClient

# Long enough to pick an account and consent; short enough that a stolen
# cookie is not worth much.
ATTEMPT_TTL_SECONDS = 600

# Google documents both spellings as issuers of its ID tokens.
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
SCOPES = ("openid", "email")

_LEEWAY_SECONDS = 30
# Keeps the attempt cookie's signature distinct from anything else signed with
# the same server secret.
_PURPOSE = b"google-sign-in-attempt"


@dataclass(frozen=True, slots=True)
class PendingSignIn:
    state: str
    nonce: str
    code_verifier: str
    started_at: int


def new_attempt(*, now: float | None = None) -> PendingSignIn:
    return PendingSignIn(
        state=secrets.token_urlsafe(32),
        nonce=secrets.token_urlsafe(32),
        # RFC 7636: 43-128 characters from the unreserved set; 64 bytes of
        # randomness encodes to 86.
        code_verifier=secrets.token_urlsafe(64),
        started_at=int(now if now is not None else time.time()),
    )


def code_challenge(verifier: str) -> str:
    """The S256 PKCE challenge for a verifier."""
    return _b64(hashlib.sha256(verifier.encode("ascii")).digest())


def seal_attempt(pending: PendingSignIn, *, secret: str) -> str:
    payload = json.dumps(
        {
            "s": pending.state,
            "n": pending.nonce,
            "v": pending.code_verifier,
            "t": pending.started_at,
        },
        separators=(",", ":"),
    ).encode()
    return f"{_b64(payload)}.{_b64(_sign(payload, secret))}"


def open_attempt(
    sealed: str | None, *, state: str, secret: str, now: float | None = None
) -> PendingSignIn:
    """The attempt this browser started, if ``state`` is the one it was given."""
    if not sealed:
        raise FederatedSignInRejectedError(
            SignInFailure.STATE_MISMATCH, "no sign-in was started from this browser"
        )
    try:
        payload_b64, signature_b64 = sealed.split(".", 1)
        payload = _unb64(payload_b64)
        signature = _unb64(signature_b64)
    except (ValueError, TypeError) as exc:
        raise FederatedSignInRejectedError(
            SignInFailure.STATE_MISMATCH, "the sign-in attempt is malformed"
        ) from exc
    if not hmac.compare_digest(signature, _sign(payload, secret)):
        raise FederatedSignInRejectedError(
            SignInFailure.STATE_MISMATCH, "the sign-in attempt does not verify"
        )

    data = json.loads(payload)
    pending = PendingSignIn(
        state=str(data["s"]),
        nonce=str(data["n"]),
        code_verifier=str(data["v"]),
        started_at=int(data["t"]),
    )
    if (now if now is not None else time.time()) - pending.started_at > ATTEMPT_TTL_SECONDS:
        raise FederatedSignInRejectedError(
            SignInFailure.EXPIRED, "this sign-in took too long; start again"
        )
    if not hmac.compare_digest(pending.state.encode(), state.encode()):
        raise FederatedSignInRejectedError(
            SignInFailure.STATE_MISMATCH, "the sign-in answer was for another attempt"
        )
    return pending


@dataclass(frozen=True, slots=True)
class GoogleEndpoints:
    """Where Google lives and who we are to it — all from configuration."""

    authorize_url: str
    token_url: str
    client_id: str
    client_secret: str
    redirect_uri: str


class GoogleIdentityProvider(Protocol):
    """The two things the flow needs from Google. Replaced by a fake in tests."""

    def authorize_url(self, pending: PendingSignIn) -> str: ...

    async def claims_for(self, *, code: str, pending: PendingSignIn) -> IdTokenClaims: ...


class GoogleOidc:
    def __init__(
        self,
        endpoints: GoogleEndpoints,
        *,
        keys: SigningKeyResolver,
        timeout_seconds: float,
        user_agent: str,
    ) -> None:
        self._endpoints = endpoints
        self._keys = keys
        self._timeout = timeout_seconds
        self._user_agent = user_agent

    def authorize_url(self, pending: PendingSignIn) -> str:
        params = {
            "client_id": self._endpoints.client_id,
            "redirect_uri": self._endpoints.redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "state": pending.state,
            "nonce": pending.nonce,
            "code_challenge": code_challenge(pending.code_verifier),
            "code_challenge_method": "S256",
            # Always show the account chooser: someone signing out and back in
            # on a shared machine should not be silently signed in as whoever
            # used Google last.
            "prompt": "select_account",
        }
        return f"{self._endpoints.authorize_url}?{urlencode(params)}"

    async def claims_for(self, *, code: str, pending: PendingSignIn) -> IdTokenClaims:
        id_token = await self._exchange(code, pending)
        # Resolving the key may fetch Google's key set, and that client blocks.
        return await asyncio.to_thread(self.decode, id_token)

    def decode(self, id_token: str) -> IdTokenClaims:
        """Check the token's signature, issuer, audience and expiry."""
        try:
            key = self._keys.get_key(id_token)
            claims: dict[str, Any] = jwt.decode(
                id_token,
                key=key,
                algorithms=["RS256"],
                audience=self._endpoints.client_id,
                issuer=GOOGLE_ISSUERS,
                leeway=_LEEWAY_SECONDS,
                options={"require": ["exp", "iat", "iss", "sub", "aud"]},
            )
        except (jwt.InvalidTokenError, DomainError) as exc:
            raise FederatedSignInRejectedError(
                SignInFailure.PROVIDER_FAILED, "Google's answer did not verify"
            ) from exc
        return _claims(claims)

    async def _exchange(self, code: str, pending: PendingSignIn) -> str:
        try:
            async with GuardedClient(
                timeout_seconds=self._timeout, user_agent=self._user_agent
            ) as client:
                response = await client.request(
                    "POST",
                    self._endpoints.token_url,
                    headers={"accept": "application/json"},
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "code_verifier": pending.code_verifier,
                        "client_id": self._endpoints.client_id,
                        "client_secret": self._endpoints.client_secret,
                        "redirect_uri": self._endpoints.redirect_uri,
                    },
                )
        except DomainError as exc:
            raise FederatedSignInRejectedError(
                SignInFailure.PROVIDER_FAILED, "Google could not be reached"
            ) from exc
        if response.status_code >= 400:
            raise FederatedSignInRejectedError(
                SignInFailure.PROVIDER_FAILED, f"Google refused the code ({response.status_code})"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise FederatedSignInRejectedError(
                SignInFailure.PROVIDER_FAILED, "Google answered with something unreadable"
            ) from exc
        token = payload.get("id_token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token:
            raise FederatedSignInRejectedError(
                SignInFailure.PROVIDER_FAILED, "Google returned no ID token"
            )
        return token


def _claims(raw: dict[str, Any]) -> IdTokenClaims:
    verified = raw.get("email_verified")
    # Google sends a boolean, but has historically sent the string "true".
    is_verified = verified is True or (isinstance(verified, str) and verified.lower() == "true")
    nonce = raw.get("nonce")
    return IdTokenClaims(
        subject=str(raw.get("sub") or ""),
        email=str(raw.get("email") or ""),
        email_verified=is_verified,
        nonce=str(nonce) if nonce is not None else None,
    )


def _sign(payload: bytes, secret: str) -> bytes:
    return hmac.new(secret.encode(), _PURPOSE + b"." + payload, hashlib.sha256).digest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
