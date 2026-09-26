"""Runs every pending migration to completion, then exits.

The `migrate` compose service, which `make migrate` runs before any app
container starts — in either mode. Alembic brings the schema to head, then
Procrastinate's job tables are applied, then the baseline crawl list is
loaded. Any failure raises and exits non-zero, so a failed migration fails the
start rather than letting the app serve on a half-migrated database.
"""

from __future__ import annotations

import asyncio

from alembic import command
from alembic.config import Config

from cli import apply_job_schema, seed_baseline


def main() -> None:
    command.upgrade(Config("alembic.ini"), "head")
    asyncio.run(apply_job_schema.main())
    asyncio.run(seed_baseline.main())


if __name__ == "__main__":
    main()
