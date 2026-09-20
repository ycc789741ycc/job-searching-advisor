"""Queued and scheduled work, on Postgres.

Phase 1 runs two queues in one worker image: ``ai`` (assessment, cluster
naming, requirement extraction, difficulty estimates, fits) and ``sync``
(connectors, resume parsing). ``docs`` and ``notify`` arrive with the Resume
and digest work in later phases. Splitting a queue into its own process group
later is a deployment change, not a code change
(docs/technical_boundaries.md section 1).
"""

from __future__ import annotations

from enum import StrEnum

from procrastinate import App, PsycopgConnector

from kernel.config import Settings


class Queue(StrEnum):
    AI = "ai"
    SYNC = "sync"


def _psycopg_dsn(sqlalchemy_url: str) -> str:
    """Procrastinate speaks psycopg; the app speaks asyncpg. Same database."""
    return sqlalchemy_url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )


def build_app(settings: Settings) -> App:
    return App(
        connector=PsycopgConnector(conninfo=_psycopg_dsn(str(settings.database_url))),
    )
