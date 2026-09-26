"""The transactional outbox.

A domain event row is written in the same transaction as the change that caused
it, so an event can never be published for a change that rolled back, and a
committed change can never lose its event. A dispatcher in ``worker`` turns
rows into queued jobs (docs/technical_boundaries.md section 2).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from kernel.db.base import Base, new_id


class OutboxEvent(Base):
    __tablename__ = "event"
    __table_args__ = (
        Index("ix_event_undispatched", "dispatched_at", postgresql_where="dispatched_at IS NULL"),
        {"schema": "outbox"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Set for events about one user. Left NULL by the crawler, which must not
    # know which users a market change affects — the dispatcher fans that out.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
