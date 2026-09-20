"""Configuration is read once, validated, and fails loudly when incomplete."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from kernel.config import MissingSecretError, Settings, get_settings
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


@pytest.mark.parametrize(
    "missing",
    ["DATABASE_URL", "CLERK_ISSUER", "CLERK_JWKS_URL", "S3_BUCKET", "GITHUB_API_BASE_URL"],
)
def test_missing_required_setting_fails_startup(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    monkeypatch.delenv(missing, raising=False)
    get_settings.cache_clear()
    with pytest.raises(PydanticValidationError):
        get_settings()


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
