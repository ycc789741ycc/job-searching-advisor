"""Signing in with Google, start to finish.

``begin`` sends the browser to Google with a fresh attempt, sealed into a
cookie. ``complete`` checks what comes back against that attempt, exchanges the
code and verifies the ID token, then hands the claims to
``AuthService.sign_in_with_google``, which issues our own session (ADR 0008).
"""

from __future__ import annotations

from dataclasses import dataclass

from advisor.identity._auth import AuthService, Session
from advisor.identity._domain import assert_acceptable_claims
from advisor.identity._infra.google import (
    GoogleIdentityProvider,
    new_attempt,
    open_attempt,
    seal_attempt,
)


@dataclass(frozen=True, slots=True)
class GoogleStart:
    redirect_url: str
    # Goes back to the browser as an httpOnly cookie. It is the only record of
    # the attempt.
    sealed_attempt: str


class GoogleSignIn:
    def __init__(self, auth: AuthService, provider: GoogleIdentityProvider, *, secret: str) -> None:
        self._auth = auth
        self._provider = provider
        self._secret = secret

    def begin(self, *, now: float | None = None) -> GoogleStart:
        pending = new_attempt(now=now)
        return GoogleStart(
            redirect_url=self._provider.authorize_url(pending),
            sealed_attempt=seal_attempt(pending, secret=self._secret),
        )

    async def complete(
        self, *, code: str, state: str, sealed_attempt: str | None, now: float | None = None
    ) -> Session:
        pending = open_attempt(sealed_attempt, state=state, secret=self._secret, now=now)
        claims = await self._provider.claims_for(code=code, pending=pending)
        assert_acceptable_claims(claims, expected_nonce=pending.nonce)
        return await self._auth.sign_in_with_google(claims)
