"""Shared fixtures.

Unit tests are hermetic: no infra, no network, no running app. Settings are
built from an explicit dict here rather than the developer's .env, so a unit
run passes on a clean checkout.
"""

from __future__ import annotations

import base64
import os
from collections.abc import Iterator

import pytest

MINIMAL_ENV = {
    "APP_ENV": "test",
    "DATABASE_URL": "postgresql+asyncpg://app_rw:pw@localhost:5432/test",
    "AUTH_JWT_SECRET": "unit-test-signing-secret-long-enough-to-pass",
    "MASTER_ENCRYPTION_KEY": base64.b64encode(b"k" * 32).decode(),
    "S3_ENDPOINT_URL": "http://objectstore:9000",
    "S3_PUBLIC_ENDPOINT_URL": "http://localhost:9000",
    "S3_REGION": "us-east-1",
    "S3_BUCKET": "test-bucket",
    "S3_ACCESS_KEY_ID": "test-access",
    "S3_SECRET_ACCESS_KEY": "test-secret",
    "OAUTH_REDIRECT_BASE_URL": "http://localhost:8000",
    "GITHUB_OAUTH_CLIENT_ID": "gh-client",
    "GITHUB_OAUTH_CLIENT_SECRET": "gh-secret",
    "GITHUB_API_BASE_URL": "https://api.github.test",
    "JIRA_OAUTH_CLIENT_ID": "jira-client",
    "JIRA_OAUTH_CLIENT_SECRET": "jira-secret",
    "JIRA_API_BASE_URL": "https://api.jira.test",
    "JIRA_OAUTH_BASE_URL": "https://auth.jira.test",
}


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A process environment holding exactly the required settings, nothing else."""
    from kernel.config import get_settings

    for key in list(os.environ):
        if key.isupper():
            monkeypatch.delenv(key, raising=False)
    for key, value in MINIMAL_ENV.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
