"""Coercion helpers for text that came from outside the system.

Shared by the crawler's board adapters and the profile connectors. Both deal
with the same problem: a field that is sometimes a string, sometimes a number,
sometimes absent, and never to be trusted.
"""

from __future__ import annotations

import html
import re
from datetime import date, datetime
from typing import Any

_TAG = re.compile(r"<[^>]+>")
_BLANKS = re.compile(r"\n{3,}")


def strip_html(raw: str) -> str:
    """Board and ticket descriptions arrive as HTML.

    It is content to analyse, never markup we render — the SPA is never handed
    external HTML.
    """
    text = html.unescape(raw or "")
    text = re.sub(r"<(br|/p|/div|/li)\s*/?>", "\n", text, flags=re.IGNORECASE)
    return _BLANKS.sub("\n\n", _TAG.sub("", text)).strip()


def parse_date(value: Any) -> date | None:
    """Accept ISO strings, epoch seconds and epoch milliseconds. Never raise."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, int | float):
        seconds = value / 1000 if value > 10_000_000_000 else value
        try:
            return datetime.fromtimestamp(seconds).date()
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    text = text.removesuffix("Z")
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None
