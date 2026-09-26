"""Tables in the ``gapplan`` schema. Owner-zone, under RLS.

A plan row holds its Target as a kind plus exactly one reference — a shared
posting, a subscription or a pasted JD — and the frozen snapshot of what that
Target required, so the plan survives posting expiry and re-clustering
(docs/technical_boundaries.md section 3). Regenerating adds a row with the next
version; nothing is overwritten.
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


class GapPlan(Base, OwnedMixin):
    __tablename__ = "plan"
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
        Index("ix_plan_owner_created", "owner_id", "created_at"),
        {"schema": "gapplan"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    target_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    job_posting_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    private_posting_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # "{role} · {company}", kept so history reads without the snapshot.
    target_label: Mapped[str] = mapped_column(String(400), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # TargetSnapshot.to_dict(): what the plan was planned against.
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # The shown gaps, ranked, each with the model's reading and its cited
    # evidence copied in, so a plan still reads if that evidence later goes.
    gaps: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'[]'::jsonb")
    )
    projects: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'[]'::jsonb")
    )
    stepping_stones: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'[]'::jsonb")
    )
    model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    template_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    drafted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Milestone(Base, OwnedMixin):
    __tablename__ = "milestone"
    __table_args__ = ({"schema": "gapplan"},)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gapplan.plan.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    # "Weeks 1-6". `window` is an SQL keyword.
    time_window: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)


class Task(Base, OwnedMixin):
    __tablename__ = "task"
    __table_args__ = ({"schema": "gapplan"},)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gapplan.plan.id", ondelete="CASCADE"), nullable=False, index=True
    )
    milestone_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gapplan.milestone.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    due: Mapped[str] = mapped_column(String(32), nullable=False)
    # The gap keys this task closes: many-to-many with the plan's gaps.
    closes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
