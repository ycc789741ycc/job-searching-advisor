"""Rules for the one AI credential in the system.

Write-only: it can be set, tested, replaced or deleted, but never read back.
What the client may see is the provider, the model and the last four
characters (docs/technical_boundaries.md section 4).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CredentialStatus(StrEnum):
    ACTIVE = "active"
    FAILED = "failed"


class Provider(StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GOOGLE = "google"
    LOCAL = "local"


# Shown in the settings screen. A user may type any model their provider
# serves; these are the ones we can price without guessing.
SUGGESTED_MODELS: dict[Provider, tuple[str, ...]] = {
    Provider.ANTHROPIC: (
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-haiku-4-5",
    ),
    Provider.OPENAI: ("gpt-5.1", "gpt-5-mini"),
    Provider.GOOGLE: ("gemini-3-pro", "gemini-3-flash"),
    Provider.LOCAL: (),
}


@dataclass(frozen=True, slots=True)
class CredentialView:
    """Everything the client is ever told about a stored credential."""

    provider: Provider
    model: str
    base_url: str | None
    last_four: str
    status: CredentialStatus
    last_error: str | None


def requires_base_url(provider: Provider) -> bool:
    """A self-hosted model has no endpoint we could know in advance."""
    return provider is Provider.LOCAL
