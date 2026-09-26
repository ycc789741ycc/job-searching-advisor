"""The current time, in one place.

Use cases take the time from here rather than from ``kernel.db``, so reading the
clock never ties business code to the database package.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)
