"""Applies Procrastinate's schema, and grants the app the rights to use it.

Runs as part of ``make migrate``, with the migrator role, so the job tables are
in place before ``start-app`` brings a worker up — never created lazily by the
first worker to connect.
"""

from __future__ import annotations

import asyncio

import psycopg

from kernel.config import get_settings
from kernel.jobs import JOB_SCHEMA, build_app
from kernel.jobs.app import _psycopg_dsn


async def main() -> None:
    settings = get_settings()
    migrator_url = _migrator_dsn()

    app = build_app(settings, url=migrator_url)
    async with app.open_async():
        await app.schema_manager.apply_schema_async()

    # The worker and api connect as app_rw, which is not the owner.
    with psycopg.connect(migrator_url, autocommit=True) as connection:
        for statement in (
            f"GRANT USAGE ON SCHEMA {JOB_SCHEMA} TO app_rw",
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {JOB_SCHEMA} TO app_rw",
            f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {JOB_SCHEMA} TO app_rw",
            f"GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA {JOB_SCHEMA} TO app_rw",
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {JOB_SCHEMA} "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_rw",
        ):
            connection.execute(statement)

    print(f"job schema applied in {JOB_SCHEMA}")


def _migrator_dsn() -> str:
    import os

    url = os.environ.get("MIGRATOR_DATABASE_URL")
    if not url:
        raise RuntimeError("MIGRATOR_DATABASE_URL is required to apply the job schema")
    return _psycopg_dsn(url)


if __name__ == "__main__":
    asyncio.run(main())
