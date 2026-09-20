"""Crawler hygiene: robots.txt, rate limits, and an identifying user agent.

This is infrastructure, not domain logic, but it is required. We crawl only
sources that permit it, and we behave on them (domain section 2.5).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser


@dataclass
class RateLimiter:
    """At most ``per_second`` requests to any one host."""

    per_second: float
    _last_call: dict[str, float] = field(default_factory=dict)

    async def wait(self, url: str) -> None:
        if self.per_second <= 0:
            return
        host = urlsplit(url).hostname or ""
        interval = 1.0 / self.per_second
        now = time.monotonic()
        earliest = self._last_call.get(host, 0.0) + interval
        if now < earliest:
            await asyncio.sleep(earliest - now)
        self._last_call[host] = time.monotonic()


class RobotsCache:
    """Remembers each host's robots.txt for the life of one crawl run."""

    def __init__(self, user_agent: str) -> None:
        self._user_agent = user_agent
        self._parsers: dict[str, RobotFileParser | None] = {}

    def remember(self, origin: str, robots_txt: str | None) -> None:
        if robots_txt is None:
            # No robots.txt means nothing is disallowed.
            self._parsers[origin] = None
            return
        parser = RobotFileParser()
        parser.parse(robots_txt.splitlines())
        self._parsers[origin] = parser

    def knows(self, origin: str) -> bool:
        return origin in self._parsers

    def allows(self, url: str) -> bool:
        parser = self._parsers.get(origin_of(url))
        return True if parser is None else bool(parser.can_fetch(self._user_agent, url))


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def robots_url_for(url: str) -> str:
    return f"{origin_of(url)}/robots.txt"
