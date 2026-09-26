"""Tables in the ``resume`` schema. Owner-zone, under RLS.

A résumé aims at one Target and stores its frozen snapshot, like a gap plan.
Its content lives in versions, never overwritten: generated, saved by hand, or
applied from the revision chat. Each revision exchange is kept with the edit it
proposed, and each export with where its PDF went.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from kernel.db.base import Base, OwnedMixin, new_id


class Resume(Base, OwnedMixin):
    __tablename__ = "resume"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(job_posting_id, subscription_id, private_posting_id) = 1",
            name="one_target",
        ),
        CheckConstraint(
            "target_kind IN ('matchedPosting', 'subscription', 'privatePosting')",
            name="target_kind",
        ),
        CheckConstraint("status IN ('drafting', 'ready', 'failed')", name="status"),
        CheckConstraint("template IN ('warm', 'plain', 'brief')", name="template"),
        Index("ix_resume_owner_updated", "owner_id", "updated_at"),
        {"schema": "resume"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    target_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    job_posting_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    private_posting_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    target_label: Mapped[str] = mapped_column(String(400), nullable=False)
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # RequirementCoverage for the snapshot: [{requirement, verdict, dimension_key,
    # evidence: [{id, reference, fact}]}].
    coverage: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'[]'::jsonb")
    )
    template: Mapped[str] = mapped_column(String(16), nullable=False)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ResumeVersion(Base, OwnedMixin):
    __tablename__ = "version"
    __table_args__ = (
        CheckConstraint("source IN ('generated', 'manual', 'chat')", name="source"),
        Index("ix_version_resume_number", "resume_id", "number", unique=True),
        {"schema": "resume"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    resume_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resume.resume.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    # ResumeContent.to_dict().
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    # Set for generated and chat versions; a manual save has no model.
    model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    template_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Revision(Base, OwnedMixin):
    """One exchange in the revision chat: the request, the reply, the edit."""

    __tablename__ = "revision"
    __table_args__ = (
        Index("ix_revision_resume_created", "resume_id", "created_at"),
        {"schema": "resume"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    resume_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resume.resume.id", ondelete="CASCADE"), nullable=False
    )
    request: Mapped[str] = mapped_column(Text, nullable=False)
    reply: Mapped[str] = mapped_column(Text, nullable=False)
    # The proposed content, validated; null when the model only advised.
    proposal: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    applied_version_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    template_version: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Export(Base, OwnedMixin):
    __tablename__ = "export"
    __table_args__ = (
        CheckConstraint("status IN ('rendering', 'ready', 'failed')", name="status"),
        {"schema": "resume"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resume.version.id", ondelete="CASCADE"), nullable=False, index=True
    )
    template: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
