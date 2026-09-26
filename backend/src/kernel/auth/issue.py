"""Issuing and verifying our own session tokens.

We run our own sign-in rather than delegating to a managed provider, so the API
issues its own short-lived access tokens. They are symmetric (HS256) and signed
with a server secret: there is exactly one issuer and one verifier, both inside
this application, so an asymmetric key pair would add moving parts without
adding a property we need.

The verification path is unchanged — ``TokenVerifier`` already takes a
``SigningKeyResolver``, so this simply supplies a static key instead of one
fetched from a JWKS endpoint.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

ALGORITHM = "HS256"


class StaticSecretResolver:
    """Supplies the one key this application signs and verifies with."""

    def __init__(self, secret: str) -> None:
        self._secret = secret

    def get_key(self, token: str) -> Any:
        return self._secret


def issue_access_token(
    *,
    secret: str,
    subject: uuid.UUID,
    email: str | None,
    issuer: str,
    audience: str,
    ttl_seconds: int,
    now: datetime | None = None,
) -> str:
    issued_at = now or datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": str(subject),
        "iss": issuer,
        "aud": audience,
        "iat": issued_at,
        "exp": issued_at + timedelta(seconds=ttl_seconds),
        # Lets a specific token be identified in a log without logging the token.
        "jti": uuid.uuid4().hex,
    }
    if email:
        claims["email"] = email
    return jwt.encode(claims, secret, algorithm=ALGORITHM)
