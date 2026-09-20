"""Alembic environment.

The URL comes from ``MIGRATOR_DATABASE_URL`` — the only role with DDL rights.
"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.models import metadata

config = context.config

url = os.environ.get("MIGRATOR_DATABASE_URL")
if not url:
    raise RuntimeError("MIGRATOR_DATABASE_URL is required to run migrations")
config.set_main_option("sqlalchemy.url", url)

target_metadata = metadata

# `public` had its default grants revoked, so Alembic's bookkeeping table gets
# a schema of its own, created by infra/bootstrap-roles.sh.
VERSION_TABLE_SCHEMA = "migrations"


def include_object(obj, name, type_, reflected, compare_to):  # type: ignore[no-untyped-def]
    # Procrastinate owns its own schema and manages its own migrations.
    schema = getattr(obj, "schema", None)
    return schema != "procrastinate"


def run_migrations_offline() -> None:
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        version_table_schema=VERSION_TABLE_SCHEMA,
        include_object=include_object,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_object=include_object,
            version_table_schema=VERSION_TABLE_SCHEMA,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
