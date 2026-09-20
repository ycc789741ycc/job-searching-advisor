"""Connector OAuth.

Separate from login OAuth in every way: different provider, different tokens,
different scopes, different storage. The two never share a code path
(docs/technical_boundaries.md section 4).

State is an HMAC over the user, the connector and a timestamp, so the callback
can be verified without a server-side session table.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from kernel.errors import UnauthenticatedError, UpstreamFailedError, ValidationError
from kernel.fetch import GuardedClient

STATE_TTL_SECONDS = 600


@dataclass(frozen=True, slots=True)
class ProviderEndpoints:
    authorize_url: str
    token_url: str
    scopes: tuple[str, ...]
    extra_authorize_params: dict[str, str]


GITHUB = ProviderEndpoints(
    authorize_url="https://github.com/login/oauth/authorize",
    token_url="https://github.com/login/oauth/access_token",  # noqa: S106 - a URL
    scopes=("read:user", "repo:status", "public_repo"),
    extra_authorize_params={},
)

JIRA = ProviderEndpoints(
    authorize_url="https://auth.atlassian.com/authorize",
    token_url="https://auth.atlassian.com/oauth/token",  # noqa: S106 - a URL
    scopes=("read:jira-work", "read:jira-user", "offline_access"),
    extra_authorize_params={"audience": "api.atlassian.com", "prompt": "consent"},
)

ENDPOINTS: dict[str, ProviderEndpoints] = {"github": GITHUB, "jira": JIRA}


def sign_state(owner_id: uuid.UUID, kind: str, *, secret: str, now: float | None = None) -> str:
    payload = json.dumps(
        {"o": str(owner_id), "k": kind, "t": int(now or time.time())},
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    return f"{_b64(payload)}.{_b64(signature)}"


def verify_state(state: str, *, secret: str, now: float | None = None) -> tuple[uuid.UUID, str]:
    try:
        payload_b64, signature_b64 = state.split(".", 1)
        payload = _unb64(payload_b64)
        signature = _unb64(signature_b64)
    except (ValueError, TypeError) as exc:
        raise UnauthenticatedError("the OAuth state is malformed") from exc

    expected = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise UnauthenticatedError("the OAuth state does not verify")

    data = json.loads(payload)
    if (now or time.time()) - float(data["t"]) > STATE_TTL_SECONDS:
        raise UnauthenticatedError("this authorization attempt expired; start again")
    return uuid.UUID(data["o"]), str(data["k"])


def authorize_url(kind: str, *, client_id: str, redirect_uri: str, state: str) -> str:
    endpoints = ENDPOINTS.get(kind)
    if endpoints is None:
        raise ValidationError(f"unknown connector {kind!r}", kind=kind)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(endpoints.scopes),
        "state": state,
        **endpoints.extra_authorize_params,
    }
    return f"{endpoints.authorize_url}?{urlencode(params)}"


async def exchange_code(
    client: GuardedClient,
    kind: str,
    *,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> dict[str, Any]:
    endpoints = ENDPOINTS.get(kind)
    if endpoints is None:
        raise ValidationError(f"unknown connector {kind!r}", kind=kind)

    response = await client.request(
        "POST",
        endpoints.token_url,
        headers={"accept": "application/json", "content-type": "application/json"},
        json={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        },
    )
    if response.status_code >= 400:
        raise UpstreamFailedError(
            f"{kind} rejected the authorization code", status=response.status_code
        )
    payload = response.json()
    if not isinstance(payload, dict) or "access_token" not in payload:
        raise UpstreamFailedError(f"{kind} returned no access token")
    return payload


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
