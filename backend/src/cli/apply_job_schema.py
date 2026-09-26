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

    # Idempotent, like every other target: applying the schema is a first-install
    # step, so it only runs when the tables are not there yet. A Procrastinate
    # version upgrade is a deliberate, separate step — see its own migrations.
    if _schema_is_applied(migrator_url):
        print(f"job schema already present in {JOB_SCHEMA}")
    else:
        app = build_app(settings, url=migrator_url)
        async with app.open_async():
            await app.schema_manager.apply_schema_async()
        print(f"job schema applied in {JOB_SCHEMA}")

    # The worker and api connect as app_rw, which is not the owner. Grants are
    # re-applied every time so a newly added table is never left unreachable.
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


def _schema_is_applied(dsn: str) -> bool:
    with psycopg.connect(dsn) as connection:
        found = connection.execute(
            "SELECT to_regclass(%s) IS NOT NULL", (f"{JOB_SCHEMA}.procrastinate_jobs",)
        ).fetchone()
    return bool(found and found[0])


def _migrator_dsn() -> str:
    import os

    url = os.environ.get("MIGRATOR_DATABASE_URL")
    if not url:
        raise RuntimeError("MIGRATOR_DATABASE_URL is required to apply the job schema")
    return _psycopg_dsn(url)


if __name__ == "__main__":
    asyncio.run(main())
