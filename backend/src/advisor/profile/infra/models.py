"""Tables in the ``profile`` schema. All owner-zone, all under RLS."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from kernel.db.base import Base, OwnedMixin, TimestampMixin, new_id


class SourceConnection(Base, OwnedMixin, TimestampMixin):
    """An authorised link to GitHub or Jira.

    Connector OAuth, not login OAuth: different tokens, different scopes,
    different revoke rules, stored separately on purpose. The tokens are
    decryptable only in the worker's ``sync`` queue.
    """

    __tablename__ = "source_connection"
    __table_args__ = (
        UniqueConstraint("owner_id", "kind", name="uq_source_connection_owner_id"),
        {"schema": "profile"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    external_account: Mapped[str | None] = mapped_column(String(255), nullable=True)
    encrypted_access_token: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    scopes: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="connected")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ResumeFile(Base, OwnedMixin, TimestampMixin):
    """An uploaded resume.

    It plays two roles: a source of Evidence, and the base document a later
    phase revises rather than replaces.
    """

    __tablename__ = "resume_file"
    __table_args__ = ({"schema": "profile"},)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="uploaded")
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Evidence(Base, OwnedMixin, TimestampMixin):
    """One cited fact. Facts only — a CareerProfile never holds a score."""

    __tablename__ = "evidence"
    __table_args__ = (
        # Re-syncing a connector must update a fact, not duplicate it.
        UniqueConstraint("owner_id", "source", "external_ref", name="uq_evidence_owner_id"),
        Index("ix_evidence_owner_source", "owner_id", "source"),
        {"schema": "profile"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    external_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    reference: Mapped[str] = mapped_column(String(512), nullable=False)
    fact: Mapped[str] = mapped_column(Text, nullable=False)
    observed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    source_connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profile.source_connection.id", ondelete="SET NULL"), nullable=True
    )
    resume_file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profile.resume_file.id", ondelete="SET NULL"), nullable=True
    )


class Position(Base, OwnedMixin, TimestampMixin):
    """The career-timeline half of a CareerProfile."""

    __tablename__ = "position"
    __table_args__ = ({"schema": "profile"},)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    started_on: Mapped[date] = mapped_column(Date, nullable=False)
    ended_on: Mapped[date | None] = mapped_column(Date, nullable=True)


class ProfileVersion(Base, OwnedMixin):
    """Bumped whenever evidence changes.

    An assessment snapshot records the version it was computed from, so a stale
    report can be detected rather than quietly shown as current.
    """

    __tablename__ = "profile_version"
    __table_args__ = (
        UniqueConstraint("owner_id", name="uq_profile_version_owner_id"),
        {"schema": "profile"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
