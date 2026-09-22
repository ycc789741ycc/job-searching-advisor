"""Market tables, split across two schemas on purpose.

``market`` is the shared zone: no ``owner_id``, no row-level security, and the
crawler role can reach it. ``market_user`` is the owner zone: every row has an
``owner_id`` and RLS, and the crawler role has no grant on it at all.

That split is what makes privacy a property of where a row lives rather than a
flag the application has to remember to check
(docs/technical_boundaries.md section 3).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from kernel.db.base import Base, OwnedMixin, TimestampMixin, new_id
from kernel.embeddings import EMBEDDING_DIMENSIONS

# --- shared zone -----------------------------------------------------------


class Company(Base, TimestampMixin):
    __tablename__ = "company"
    __table_args__ = ({"schema": "market"},)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    website: Mapped[str | None] = mapped_column(String(512), nullable=True)


class CrawlSource(Base, TimestampMixin):
    """A crawlable endpoint.

    Materialised from ``market_user`` by a worker job **without user ids**, so
    the crawler cannot work out who asked for a company.
    """

    __tablename__ = "crawl_source"
    __table_args__ = (
        UniqueConstraint("kind", "endpoint", name="uq_crawl_source_kind"),
        {"schema": "market"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("market.company.id", ondelete="CASCADE"), nullable=True
    )
    market: Mapped[str | None] = mapped_column(String(128), nullable=True)
    endpoint: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class JobPosting(Base, TimestampMixin):
    """One normalised opening, shared by every user.

    Pasted JDs are *not* here — they live in ``market_user.private_job_posting``
    where the crawler role physically cannot reach them (domain decision 12).
    """

    __tablename__ = "job_posting"
    __table_args__ = (
        UniqueConstraint("canonical_key", name="uq_job_posting_canonical_key"),
        Index("ix_job_posting_status_seen", "status", "last_seen_at"),
        {"schema": "market"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    canonical_key: Mapped[str] = mapped_column(String(768), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("market.company.id", ondelete="CASCADE"), nullable=False, index=True
    )
    crawl_source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("market.crawl_source.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    posted_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    # An expired posting still counts toward salary-band history; it just drops
    # out of the jobs list and the opening counts.
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PostingEmbedding(Base):
    """Local embedding of a posting. Plain computation, paid by the platform."""

    __tablename__ = "posting_embedding"
    __table_args__ = ({"schema": "market"},)

    job_posting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("market.job_posting.id", ondelete="CASCADE"), primary_key=True
    )
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    vector: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --- owner zone ------------------------------------------------------------


class CompanySubscription(Base, OwnedMixin, TimestampMixin):
    """A RoleSubscription: a watch on one role at one company (domain decision 19).

    The table keeps its original name, which the fan-out RLS policy is keyed on;
    a user can watch several roles at the same company.
    """

    __tablename__ = "company_subscription"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "company_id", "role_title", name="uq_company_subscription_owner_id"
        ),
        {"schema": "market_user"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    company_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # The role's name when the user subscribed. Roles are per user and can be
    # retired by a recluster, so the title is what persists; `role_id` points
    # at the user's role while it exists.
    role_title: Mapped[str] = mapped_column(String(255), nullable=False, server_default="")
    role_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # A careers page or JD link. It seeds board discovery and is never shown
    # to the crawler with an owner attached.
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # `crawled` when a supported board was found, otherwise `manual`, which
    # offers "paste a JD" and is re-checked weekly (domain decision 13).
    coverage: Mapped[str] = mapped_column(String(16), nullable=False, server_default="manual")
    last_refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class MarketPreference(Base, OwnedMixin, TimestampMixin):
    """A location or remote region the user chose. There is no fixed list."""

    __tablename__ = "market_preference"
    __table_args__ = (
        UniqueConstraint("owner_id", "market", name="uq_market_preference_owner_id"),
        {"schema": "market_user"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    market: Mapped[str] = mapped_column(String(128), nullable=False)


class PrivateJobPosting(Base, OwnedMixin, TimestampMixin):
    """A JD the user pasted. Used only for its owner.

    It appears in the owner's role map, fit scoring and resume tailoring, and
    never in anyone else's clustering, jobs list or salary bands.
    """

    __tablename__ = "private_job_posting"
    __table_args__ = ({"schema": "market_user"},)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    canonical_key: Mapped[str] = mapped_column(String(768), nullable=False, index=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # One-way link to a matching crawled posting, so the user gets weekly
    # updates. Nothing ever flows back the other way.
    shared_posting_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    vector: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=True)


class ManualRefreshLog(Base, OwnedMixin):
    """Backs the per-day cap on manual single-company re-crawls."""

    __tablename__ = "manual_refresh_log"
    __table_args__ = (
        Index("ix_manual_refresh_log_owner_day", "owner_id", "requested_at"),
        {"schema": "market_user"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    company_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
