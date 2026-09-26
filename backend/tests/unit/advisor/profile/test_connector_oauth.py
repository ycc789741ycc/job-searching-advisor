"""Connector OAuth state: signed, scoped to one user, and short-lived."""

from __future__ import annotations

import uuid

import pytest

from advisor.profile.infra.oauth import (
    STATE_TTL_SECONDS,
    authorize_url,
    endpoints_for,
    sign_state,
    verify_state,
)
from kernel.errors import UnauthenticatedError, ValidationError

SECRET = "test-signing-secret"
JIRA_BASE = "https://auth.atlassian.com"
OWNER = uuid.UUID("11111111-1111-1111-1111-111111111111")


def test_state_round_trips_to_its_user_and_connector() -> None:
    state = sign_state(OWNER, "github", secret=SECRET)
    assert verify_state(state, secret=SECRET) == (OWNER, "github")


def test_state_signed_with_another_secret_is_refused() -> None:
    state = sign_state(OWNER, "github", secret=SECRET)
    with pytest.raises(UnauthenticatedError, match="does not verify"):
        verify_state(state, secret="a-different-secret")


def test_a_tampered_state_is_refused() -> None:
    """Swapping the user in the payload must not survive the signature."""
    state = sign_state(OWNER, "github", secret=SECRET)
    _payload, signature = state.split(".", 1)
    forged = sign_state(uuid.uuid4(), "github", secret="attacker").split(".", 1)[0]
    with pytest.raises(UnauthenticatedError):
        verify_state(f"{forged}.{signature}", secret=SECRET)


def test_an_expired_state_is_refused() -> None:
    state = sign_state(OWNER, "github", secret=SECRET, now=1_000_000)
    with pytest.raises(UnauthenticatedError, match="expired"):
        verify_state(state, secret=SECRET, now=1_000_000 + STATE_TTL_SECONDS + 1)


def test_a_state_just_inside_the_window_is_accepted() -> None:
    state = sign_state(OWNER, "github", secret=SECRET, now=1_000_000)
    assert verify_state(state, secret=SECRET, now=1_000_000 + STATE_TTL_SECONDS - 1)[0] == OWNER


def test_garbage_is_refused_rather_than_crashing() -> None:
    with pytest.raises(UnauthenticatedError, match="malformed"):
        verify_state("not-a-state", secret=SECRET)


def test_the_authorize_url_carries_the_scopes_and_state() -> None:
    url = authorize_url(
        "github",
        jira_oauth_base=JIRA_BASE,
        client_id="client-123",
        redirect_uri="https://app.test/callback",
        state="the-state",
    )
    assert url.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=client-123" in url
    assert "state=the-state" in url
    assert "read%3Auser" in url


def test_jira_asks_for_offline_access_so_the_weekly_sync_keeps_working() -> None:
    url = authorize_url(
        "jira",
        jira_oauth_base=JIRA_BASE,
        client_id="c",
        redirect_uri="https://app.test/cb",
        state="s",
    )
    assert "offline_access" in url
    assert "audience=api.atlassian.com" in url


def test_an_unknown_connector_is_refused() -> None:
    with pytest.raises(ValidationError, match="unknown connector"):
        authorize_url(
            "linkedin", jira_oauth_base=JIRA_BASE, client_id="c", redirect_uri="r", state="s"
        )


def test_jira_uses_the_configured_oauth_host_not_a_literal() -> None:
    """JIRA_OAUTH_BASE_URL used to be declared and silently ignored."""
    endpoints = endpoints_for("jira", jira_oauth_base="https://auth.example.test/")
    assert endpoints.authorize_url == "https://auth.example.test/authorize"
    assert endpoints.token_url == "https://auth.example.test/oauth/token"


def test_the_authorize_url_carries_the_redirect_the_provider_must_return_to() -> None:
    """The redirect is the SPA's page, which forwards code and state to the API."""
    url = authorize_url(
        "jira",
        jira_oauth_base=JIRA_BASE,
        client_id="c",
        redirect_uri="http://localhost:5173/connections/jira/callback",
        state="s",
    )
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A5173%2Fconnections%2Fjira%2Fcallback" in url
