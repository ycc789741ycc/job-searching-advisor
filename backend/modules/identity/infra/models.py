"""Tables in the ``identity`` schema. All owner-zone, all under RLS."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from kernel.db.base import Base, OwnedMixin, TimestampMixin, new_id


class Account(Base, TimestampMixin):
    """A person using the app.

    Identity itself lives with the auth provider; this row is the local anchor
    every owner-zone table points at. ``auth_subject`` is the provider's stable
    user id, never an email — emails change.
    """

    __tablename__ = "account"
    __table_args__ = ({"schema": "identity"},)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    auth_subject: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    # Set when ProviderCredentialFailed or UsageBudgetExceeded pauses this
    # user's scheduled work, so nothing silently runs up a bill or goes stale.
    background_jobs_paused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paused_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


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
