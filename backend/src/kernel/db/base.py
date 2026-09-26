"""Declarative base and the column conventions every table follows."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Kept importable from here for existing callers; new code takes it from kernel.clock.
from kernel.clock import utcnow as utcnow

# snake_case names, and one predictable constraint-naming scheme so Alembic can
# autogenerate reversible migrations.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def new_id() -> uuid.UUID:
    return uuid.uuid4()


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class OwnedMixin:
    """Marks a row as living in the owner zone.

    Every table with this mixin carries ``owner_id`` and is covered by a
    row-level-security policy keyed on the ``app.user_id`` transaction setting.
    Privacy comes from where a row is stored, not from a flag the application
    remembers to check (docs/technical_boundaries.md section 3).
    """

    owner_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
