"""Identity's entities: accounts and how they sign in, the AI credential, the
budget that guards it, and the ledger of what it spent.

Plain data with the rules that belong to it; ``advisor.identity.infra`` maps
these to and from the database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from advisor.identity.domain.credential import CredentialStatus, Provider
from advisor.identity.domain.password import LockoutState
from advisor.identity.domain.tokens import RefreshTokenState


@dataclass(slots=True)
class Account:
    """A person using the app, and the subject of the tokens we issue.

    ``email`` is stored normalised, so there is one account per address.
    """

    id: uuid.UUID
    email: str
    background_jobs_paused_at: datetime | None = None
    paused_reason: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def registered(cls, email: str) -> Account:
        return cls(id=uuid.uuid4(), email=email)

    def pause_background_jobs(self, reason: str, *, at: datetime) -> None:
        """A failed key or an exhausted budget pauses scheduled work, so
        nothing silently runs up a bill or goes stale."""
        self.background_jobs_paused_at = at
        self.paused_reason = reason

    def resume_background_jobs(self) -> None:
        self.background_jobs_paused_at = None
        self.paused_reason = None


@dataclass(slots=True)
class PasswordCredential:
    id: uuid.UUID
    account_id: uuid.UUID
    password_hash: str
    failed_attempts: int
    last_failed_at: datetime | None
    password_updated_at: datetime
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def set_for(
        cls, account_id: uuid.UUID, *, password_hash: str, at: datetime
    ) -> PasswordCredential:
        return cls(
            id=uuid.uuid4(),
            account_id=account_id,
            password_hash=password_hash,
            failed_attempts=0,
            last_failed_at=None,
            password_updated_at=at,
        )

    @property
    def lockout(self) -> LockoutState:
        return LockoutState(
            failed_attempts=self.failed_attempts, last_failed_at=self.last_failed_at
        )

    def record_lockout(self, state: LockoutState) -> None:
        self.failed_attempts = state.failed_attempts
        self.last_failed_at = state.last_failed_at

    def rehash(self, password_hash: str, *, at: datetime) -> None:
        self.password_hash = password_hash
        self.password_updated_at = at


@dataclass(slots=True)
class FederatedIdentity:
    """An outside identity (Google's ``sub``) linked to one of our accounts."""

    id: uuid.UUID
    account_id: uuid.UUID
    provider: str
    subject: str
    email_at_link: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def linked(
        cls, account_id: uuid.UUID, *, provider: str, subject: str, email: str
    ) -> FederatedIdentity:
        return cls(
            id=uuid.uuid4(),
            account_id=account_id,
            provider=provider,
            subject=subject,
            email_at_link=email,
        )


@dataclass(slots=True)
class RefreshToken:
    """One issued refresh token, held only as a digest.

    ``family_id`` ties a rotation chain together, so a reused token can take
    the whole chain down with it.
    """

    id: uuid.UUID
    account_id: uuid.UUID
    token_hash: str
    family_id: uuid.UUID
    expires_at: datetime
    used_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime | None = None

    @classmethod
    def issued(
        cls,
        account_id: uuid.UUID,
        *,
        token_hash: str,
        family_id: uuid.UUID,
        expires_at: datetime,
    ) -> RefreshToken:
        return cls(
            id=uuid.uuid4(),
            account_id=account_id,
            token_hash=token_hash,
            family_id=family_id,
            expires_at=expires_at,
        )

    @property
    def state(self) -> RefreshTokenState:
        return RefreshTokenState(
            expires_at=self.expires_at, revoked_at=self.revoked_at, used_at=self.used_at
        )

    def use(self, at: datetime) -> None:
        """Single-use: rotation spends a token the moment it is exchanged."""
        self.used_at = at


@dataclass(slots=True)
class ProviderCredential:
    """The user's AI provider and key. Written, tested, replaced — never read
    back in the clear."""

    id: uuid.UUID
    owner_id: uuid.UUID
    provider: Provider
    model: str
    base_url: str | None
    # Envelope-encrypted, bound to owner_id as additional authenticated data.
    encrypted_api_key: str
    # The only part of the key the client may ever see.
    last_four: str
    status: CredentialStatus
    last_error: str | None = None
    last_verified_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def configured(
        cls,
        owner_id: uuid.UUID,
        *,
        provider: Provider,
        model: str,
        base_url: str | None,
        encrypted_api_key: str,
        last_four: str,
    ) -> ProviderCredential:
        return cls(
            id=uuid.uuid4(),
            owner_id=owner_id,
            provider=provider,
            model=model,
            base_url=base_url,
            encrypted_api_key=encrypted_api_key,
            last_four=last_four,
            status=CredentialStatus.ACTIVE,
        )

    def failed(self, reason: str) -> None:
        self.status = CredentialStatus.FAILED
        self.last_error = reason


@dataclass(slots=True)
class AiUsageBudget:
    id: uuid.UUID
    owner_id: uuid.UUID
    monthly_cap_usd: Decimal
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def capped(cls, owner_id: uuid.UUID, monthly_cap_usd: Decimal) -> AiUsageBudget:
        return cls(id=uuid.uuid4(), owner_id=owner_id, monthly_cap_usd=monthly_cap_usd)


@dataclass(slots=True)
class AiUsageEntry:
    """One AI call, including calls whose output was then rejected — the
    provider billed for those too."""

    id: uuid.UUID
    owner_id: uuid.UUID
    task: str
    provider: str
    model: str
    template_version: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    occurred_at: datetime
