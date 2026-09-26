"""Configuration is read once, validated, and fails loudly when incomplete."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from kernel.config import MissingSecretError, Settings, Unit, get_settings
from tests.conftest import MINIMAL_ENV


def test_required_settings_build_with_documented_defaults(clean_env: None) -> None:
    settings = get_settings()
    assert settings.app_env == "test"
    # Optional, non-sensitive settings may default; everything else may not.
    assert settings.port == 8000
    assert settings.log_level == "INFO"
    assert settings.signed_url_ttl_seconds == 300


def test_settings_are_read_once(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    first = get_settings()
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    assert get_settings() is first, "settings must be read once at startup, not per call"


@pytest.mark.parametrize("missing", ["APP_ENV"])
def test_a_universally_required_setting_fails_startup(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    """A setting every process needs is enforced by the schema itself."""
    monkeypatch.delenv(missing, raising=False)
    get_settings.cache_clear()
    with pytest.raises(PydanticValidationError):
        get_settings()


@pytest.mark.parametrize(
    ("unit", "missing"),
    [
        (Unit.API, "AUTH_JWT_SECRET"),
        (Unit.API, "DATABASE_URL"),
        (Unit.API, "S3_BUCKET"),
        (Unit.API, "GITHUB_API_BASE_URL"),
        (Unit.WORKER, "MASTER_ENCRYPTION_KEY"),
        (Unit.WORKER, "S3_SECRET_ACCESS_KEY"),
        (Unit.CRAWLER, "CRAWLER_DATABASE_URL"),
    ],
)
def test_a_unit_refuses_to_start_without_what_it_needs(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, unit: Unit, missing: str
) -> None:
    """Per-unit, because the three deployables need different configuration —
    and deliberately must not hold each other's secrets."""
    monkeypatch.setenv("CRAWLER_DATABASE_URL", "postgresql+asyncpg://c:p@postgres:5432/t")
    monkeypatch.setenv("AUTH_JWT_SECRET", "x" * 48)
    monkeypatch.delenv(missing, raising=False)
    get_settings.cache_clear()
    with pytest.raises(MissingSecretError, match=missing):
        get_settings().require_for(unit)


def test_the_crawler_needs_no_secrets_at_all(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The crawler parses hostile HTML, so it holds nothing worth stealing."""
    for name in (
        "MASTER_ENCRYPTION_KEY",
        "DATABASE_URL",
        "AUTH_JWT_SECRET",
        "S3_ENDPOINT_URL",
        "S3_PUBLIC_ENDPOINT_URL",
        "S3_REGION",
        "S3_BUCKET",
        "S3_ACCESS_KEY_ID",
        "S3_SECRET_ACCESS_KEY",
        "GITHUB_OAUTH_CLIENT_ID",
        "GITHUB_OAUTH_CLIENT_SECRET",
        "GITHUB_API_BASE_URL",
        "JIRA_OAUTH_CLIENT_ID",
        "JIRA_OAUTH_CLIENT_SECRET",
        "JIRA_API_BASE_URL",
        "JIRA_OAUTH_BASE_URL",
        "OAUTH_REDIRECT_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CRAWLER_DATABASE_URL", "postgresql+asyncpg://c:p@postgres:5432/t")
    get_settings.cache_clear()

    settings = get_settings()
    settings.require_for(Unit.CRAWLER)

    assert settings.master_encryption_key is None
    assert settings.database_url is None
    assert settings.github_oauth_client_secret is None
    with pytest.raises(MissingSecretError, match="must not hold app_rw"):
        settings.require_database_url()
    for unit in (Unit.API, Unit.WORKER):
        with pytest.raises(MissingSecretError):
            settings.require_for(unit)


def test_cors_origins_are_parsed_from_a_list(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173, https://app.test")
    get_settings.cache_clear()
    assert get_settings().cors_origins == ["http://localhost:5173", "https://app.test"]


def test_log_level_must_be_known(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "chatty")
    get_settings.cache_clear()
    with pytest.raises(PydanticValidationError):
        get_settings()


def test_master_key_absent_fails_loudly_rather_than_silently(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The crawler runs without the master key on purpose."""
    monkeypatch.delenv("MASTER_ENCRYPTION_KEY", raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.master_encryption_key is None
    with pytest.raises(MissingSecretError, match="never on `crawler`"):
        settings.require_master_key()


def test_confidence_threshold_must_be_a_probability(monkeypatch: pytest.MonkeyPatch) -> None:
    env = dict(MINIMAL_ENV, ASSESSMENT_CONFIDENCE_THRESHOLD="1.5")
    with pytest.raises(PydanticValidationError):
        Settings(**{k.lower(): v for k, v in env.items()})  # type: ignore[arg-type]


def test_google_sign_in_is_off_until_a_client_id_is_set(clean_env: None) -> None:
    settings = get_settings()
    assert not settings.google_sign_in_enabled
    settings.require_for(Unit.API)


@pytest.mark.parametrize(
    "missing",
    [
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "GOOGLE_OAUTH_AUTHORIZE_URL",
        "GOOGLE_OAUTH_TOKEN_URL",
        "GOOGLE_OAUTH_JWKS_URL",
        "AUTH_PUBLIC_API_BASE_URL",
    ],
)
def test_switching_google_on_makes_the_rest_of_it_required(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    google = {
        "GOOGLE_OAUTH_CLIENT_ID": "client.apps.googleusercontent.test",
        "GOOGLE_OAUTH_CLIENT_SECRET": "secret",
        "GOOGLE_OAUTH_AUTHORIZE_URL": "https://accounts.google.test/o/oauth2/v2/auth",
        "GOOGLE_OAUTH_TOKEN_URL": "https://oauth2.google.test/token",
        "GOOGLE_OAUTH_JWKS_URL": "https://www.google.test/oauth2/v3/certs",
        "AUTH_PUBLIC_API_BASE_URL": "http://localhost:21470",
    }
    for name, value in google.items():
        if name != missing:
            monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.google_sign_in_enabled
    with pytest.raises(MissingSecretError, match=missing):
        settings.require_for(Unit.API)
    # The worker never signs anyone in, so it does not need any of it.
    settings.require_for(Unit.WORKER)
