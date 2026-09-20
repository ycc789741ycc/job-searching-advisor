#!/usr/bin/env bash
# Creates the least-privilege database roles from docs/technical_boundaries.md
# section 3, and the extensions the schema needs. Idempotent.
#
# Roles only — the GRANTs and row-level-security policies belong with the
# schema and are applied by Alembic, because they reference tables that do not
# exist yet at this point.
set -euo pipefail
cd "$(dirname "$0")/.."

set -a; . ./"${ENV_FILE:-.env}"; set +a
: "${POSTGRES_SUPERUSER:?}" "${POSTGRES_DB:?}"
: "${APP_RW_PASSWORD:?}" "${CRAWLER_RW_PASSWORD:?}" "${AGGREGATOR_PASSWORD:?}" "${MIGRATOR_PASSWORD:?}"

COMPOSE=(docker compose --env-file "${ENV_FILE:-.env}" -f infra/compose.yml)

psql_super() {
  "${COMPOSE[@]}" exec -T -e PGPASSWORD="$POSTGRES_SUPERUSER_PASSWORD" postgres \
    psql -v ON_ERROR_STOP=1 -U "$POSTGRES_SUPERUSER" -d "$POSTGRES_DB" "$@"
}

ensure_role() {
  local role="$1" password="$2"
  psql_super -q <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${role}') THEN
    EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', '${role}', '${password}');
  ELSE
    EXECUTE format('ALTER ROLE %I LOGIN PASSWORD %L', '${role}', '${password}');
  END IF;
END
\$\$;
SQL
}

ensure_role app_rw      "$APP_RW_PASSWORD"
ensure_role crawler_rw  "$CRAWLER_RW_PASSWORD"
ensure_role aggregator  "$AGGREGATOR_PASSWORD"
ensure_role migrator    "$MIGRATOR_PASSWORD"

# migrator owns the schema, so it needs DDL rights on the database.
psql_super -q -c "GRANT CREATE, CONNECT ON DATABASE \"$POSTGRES_DB\" TO migrator;"
psql_super -q -c "GRANT CONNECT ON DATABASE \"$POSTGRES_DB\" TO app_rw, crawler_rw, aggregator;"

# Nobody gets the implicit public-schema rights Postgres hands out by default.
psql_super -q -c "REVOKE ALL ON SCHEMA public FROM PUBLIC;"

psql_super -q -c "CREATE EXTENSION IF NOT EXISTS vector;"
psql_super -q -c "CREATE EXTENSION IF NOT EXISTS pgcrypto;"

echo "database roles and extensions ready"
