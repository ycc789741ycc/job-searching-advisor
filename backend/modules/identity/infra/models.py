"""Tables in the ``identity`` schema. All owner-zone, all under RLS."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from kernel.db.base import Base, OwnedMixin, TimestampMixin, new_id


class Account(Base, TimestampMixin):
    """A person using the app.

    This row is the anchor every owner-zone table points at, and the subject of
    the access tokens we issue.

    ``email`` is the identifier someone signs in with, stored normalised so
    there is one account per address however it was typed. ``auth_subject``
    stays for a later external identity (Google in Phase 2) and is null for an
    account that only has a password.
    """

    __tablename__ = "account"
    __table_args__ = ({"schema": "identity"},)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    auth_subject: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    # Set when ProviderCredentialFailed or UsageBudgetExceeded pauses this
    # user's scheduled work, so nothing silently runs up a bill or goes stale.
    background_jobs_paused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paused_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class PasswordCredential(Base, OwnedMixin, TimestampMixin):
    """An account's password, and the state that resists guessing it.

    Separate from ``account`` so a future sign-in method sits beside it rather
    than adding more nullable columns to the row everything else points at.
    """

    __tablename__ = "password_credential"
    __table_args__ = (
        UniqueConstraint("owner_id", name="uq_password_credential_owner_id"),
        {"schema": "identity"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("identity.account.id", ondelete="CASCADE"), nullable=False
    )
    # Argon2id, which encodes its own parameters, so raising the cost later is
    # a change in one place and old hashes still verify.
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RefreshToken(Base, OwnedMixin):
    """One issued refresh token.

    Stored as a SHA-256 digest, not in the clear: a database leak must not hand
    over live sessions. The token is 32 random bytes, so a fast digest is right
    here — there is nothing to brute-force, unlike a password.

    ``family_id`` ties a rotation chain together. Presenting an already-used
    token means a replay or a theft and we cannot tell which, so the whole
    family is revoked.
    """

    __tablename__ = "refresh_token"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_refresh_token_token_hash"),
        Index("ix_refresh_token_owner_family", "owner_id", "family_id"),
        {"schema": "identity"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("identity.account.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    family_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProviderCredential(Base, OwnedMixin, TimestampMixin):
    """The user's AI provider and key. Written, tested, replaced — never read."""

    __tablename__ = "provider_credential"
    __table_args__ = (
        UniqueConstraint("owner_id", name="uq_provider_credential_owner_id"),
        {"schema": "identity"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Envelope-encrypted, bound to owner_id as additional authenticated data.
    encrypted_api_key: Mapped[str] = mapped_column(Text, nullable=False)
    # The only part of the key the client may ever see.
    last_four: Mapped[str] = mapped_column(String(4), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AiUsageBudget(Base, OwnedMixin, TimestampMixin):
    __tablename__ = "ai_usage_budget"
    __table_args__ = (
        UniqueConstraint("owner_id", name="uq_ai_usage_budget_owner_id"),
        {"schema": "identity"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    monthly_cap_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)


class AiUsageLedger(Base, OwnedMixin):
    """One row per AI call, including calls whose output we then rejected —
    the provider billed for those too."""

    __tablename__ = "ai_usage_ledger"
    __table_args__ = (
        Index("ix_ai_usage_ledger_owner_occurred", "owner_id", "occurred_at"),
        {"schema": "identity"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("identity.account.id", ondelete="CASCADE"), nullable=False
    )
    task: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    template_version: Mapped[str] = mapped_column(String(128), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
