"""JWT verification.

Signature, issuer, audience and expiry are checked on every request. The key
comes from a ``SigningKeyResolver``, so this module does not care whether the
token was issued by this application (``StaticSecretResolver``) or by an
external OpenID provider (``JwksResolver``) — which is what keeps a later move
to hosted sign-in a wiring change rather than a rewrite.

Connector OAuth (GitHub, Jira) is a separate flow with separate token storage
and never touches this module (docs/technical_boundaries.md section 4).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol

import jwt
from jwt import PyJWKClient

from kernel.errors import UnauthenticatedError

_LEEWAY_SECONDS = 30


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """Who the request is from. ``subject`` is the provider's stable user id."""

    subject: str
    email: str | None
    session_id: str | None


class SigningKeyResolver(Protocol):
    """Returns the PEM/public key for a token. Stubbed in tests."""

    def get_key(self, token: str) -> Any: ...


class JwksResolver:
    """Fetches and caches the provider's public keys."""

    def __init__(self, jwks_url: str, cache_seconds: int) -> None:
        self._client = PyJWKClient(jwks_url, cache_keys=True, lifespan=cache_seconds)

    def get_key(self, token: str) -> Any:
        try:
            return self._client.get_signing_key_from_jwt(token).key
        except Exception as exc:
            raise UnauthenticatedError("token signing key could not be resolved") from exc


class TokenVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        resolver: SigningKeyResolver,
        algorithms: tuple[str, ...] = ("RS256",),
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._resolver = resolver
        self._algorithms = list(algorithms)

    def verify(self, token: str) -> AuthenticatedUser:
        key = self._resolver.get_key(token)
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key,
                algorithms=self._algorithms,
                audience=self._audience,
                issuer=self._issuer,
                leeway=_LEEWAY_SECONDS,
                options={
                    "require": ["exp", "iat", "iss", "sub", "aud"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_aud": True,
                    "verify_iss": True,
                },
            )
        except jwt.ExpiredSignatureError as exc:
            raise UnauthenticatedError("token has expired") from exc
        except jwt.InvalidTokenError as exc:
            # Deliberately vague to the caller; the detail is logged, not returned.
            raise UnauthenticatedError("token is not valid") from exc

        # `nbf` is optional in Clerk tokens but honoured when present.
        not_before = claims.get("nbf")
        if not_before is not None and time.time() + _LEEWAY_SECONDS < float(not_before):
            raise UnauthenticatedError("token is not valid yet")

        subject = str(claims["sub"])
        if not subject:
            raise UnauthenticatedError("token has no subject")

        return AuthenticatedUser(
            subject=subject,
            email=claims.get("email"),
            session_id=claims.get("sid"),
        )
