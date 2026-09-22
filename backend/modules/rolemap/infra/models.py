"""Tables in the ``rolemap`` schema.

Roles are grouped per user, over that user's markets and subscriptions, and
computed on that user's key — so this is owner-zone, under RLS, even though
the postings underneath it are shared (domain decision 7).
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


class Role(Base, OwnedMixin, TimestampMixin):
    """A cluster of postings in one user's markets.

    ``id`` is stable across re-clustering: goals and fits point at it, so
    renumbering on every crawl would break them.
    """

    __tablename__ = "role"
    __table_args__ = (
        Index("ix_role_owner_name", "owner_id", "name"),
        {"schema": "rolemap"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_coherent: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    opening_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # Hiring bar: the bubble chart's X axis.
    hiring_bar: Mapped[int] = mapped_column(Integer, nullable=False, server_default="50")
    bar_confidence: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    bar_basis: Mapped[str] = mapped_column(String(16), nullable=False, server_default="estimated")
    bar_sample_size: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    bar_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Salary bands per selected market: {"Berlin": {...}, "Remote EU": {...}}.
    salary_bands: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")

    model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    template_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RoleMember(Base, OwnedMixin):
    """Which postings a role was built from. One of the two ids is set."""

    __tablename__ = "role_member"
    __table_args__ = (
        UniqueConstraint("role_id", "posting_key", name="uq_role_member_role_id"),
        {"schema": "rolemap"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rolemap.role.id", ondelete="CASCADE"), nullable=False
    )
    # The shared posting id, or "private:<id>" for a pasted JD. Kept as text so
    # reconciliation compares the same keys the domain works with.
    posting_key: Mapped[str] = mapped_column(String(128), nullable=False)


class RoleRequirement(Base, OwnedMixin):
    """Free text pulled from a role's postings. It has no dimension."""

    __tablename__ = "role_requirement"
    __table_args__ = ({"schema": "rolemap"},)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rolemap.role.id", ondelete="CASCADE"), nullable=False, index=True
    )
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    expected_level: Mapped[str] = mapped_column(String(32), nullable=False)


class RoleLineage(Base, OwnedMixin):
    """Added, split, merged and retired, with parents.

    A goal pointing at a role that split needs to be able to find the successor
    with the most requirement overlap.
    """

    __tablename__ = "role_lineage"
    __table_args__ = ({"schema": "rolemap"},)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    role_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    from_role_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RoleMapSetting(Base, OwnedMixin, TimestampMixin):
    """How many roles this user's role map analyses (ADR 0003).

    One row per user; no row means the default. The bound is a domain rule in
    ``domain.rolemap``, checked before anything is stored here.
    """

    __tablename__ = "role_map_setting"
    __table_args__ = (
        UniqueConstraint("owner_id", name="uq_role_map_setting_owner_id"),
        {"schema": "rolemap"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    role_count: Mapped[int] = mapped_column(Integer, nullable=False)
