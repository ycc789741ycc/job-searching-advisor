"""Tables in the ``assessment`` schema. Owner-zone, under RLS.

Assessments and fits are **immutable snapshots**. Each records the profile
version, model id and template version it came from, so a saved result can say
what it was based on and a stale one can be detected (domain section 2.4).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from kernel.db.base import Base, OwnedMixin, TimestampMixin, new_id


class SkillDimension(Base, OwnedMixin, TimestampMixin):
    """One axis of *this user's* skills. There is no global taxonomy.

    ``key`` is the stable id reused across re-assessments; without it, progress
    could not be shown by comparing two assessments.
    """

    __tablename__ = "skill_dimension"
    __table_args__ = (
        UniqueConstraint("owner_id", "key", name="uq_skill_dimension_owner_id"),
        {"schema": "assessment"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    short_name: Mapped[str] = mapped_column(String(32), nullable=False)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SkillAssessment(Base, OwnedMixin):
    __tablename__ = "skill_assessment"
    __table_args__ = (
        Index("ix_skill_assessment_owner_created", "owner_id", "created_at"),
        {"schema": "assessment"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    template_version: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DimensionScore(Base, OwnedMixin):
    __tablename__ = "dimension_score"
    __table_args__ = (
        UniqueConstraint("assessment_id", "dimension_key", name="uq_dimension_score_assessment_id"),
        {"schema": "assessment"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessment.skill_assessment.id", ondelete="CASCADE"), nullable=False
    )
    dimension_key: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    read: Mapped[str] = mapped_column(Text, nullable=False)
    # Evidence ids, each verified to belong to this user before the row exists.
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)


class DimensionLineage(Base, OwnedMixin):
    """Added, renamed and merged, so radar history still lines up."""

    __tablename__ = "dimension_lineage"
    __table_args__ = ({"schema": "assessment"},)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessment.skill_assessment.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    dimension_key: Mapped[str] = mapped_column(String(64), nullable=False)
    from_keys: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    previous_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FollowUpQuestion(Base, OwnedMixin):
    """Raised when a dimension's confidence is below the threshold."""

    __tablename__ = "follow_up_question"
    __table_args__ = (
        Index("ix_follow_up_question_owner_answered", "owner_id", "answered_at"),
        {"schema": "assessment"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessment.skill_assessment.id", ondelete="CASCADE"), nullable=False
    )
    dimension_key: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    why: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RoleFit(Base, OwnedMixin):
    """A snapshot of fit between this user and one role or posting.

    Fit lives here, on the User x Role pair — never as an attribute of a role.
    """

    __tablename__ = "role_fit"
    __table_args__ = (
        Index("ix_role_fit_owner_target", "owner_id", "role_id", "created_at"),
        {"schema": "assessment"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    assessment_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # Exactly one of these is set.
    role_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    private_posting_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    # The projection is an AI judgement, so it is stored with its reasoning and
    # shown to the user.
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    target_profile: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    gaps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    uncovered: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    template_version: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
