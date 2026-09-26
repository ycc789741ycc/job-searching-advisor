#!/usr/bin/env bash
# Where this stack's disk goes: free space on the disk the volumes live on,
# each volume's size, the largest Postgres relations, and object storage by
# bucket. Read-only, and every tool runs inside a container that already has
# it — no psql or mc on the host. Needs infra up.
set -euo pipefail
cd "$(dirname "$0")/.."

set -a; . ./"${ENV_FILE:-.env}"; set +a
: "${POSTGRES_SUPERUSER:?}" "${POSTGRES_DB:?}"

COMPOSE=(docker compose --env-file "${ENV_FILE:-.env}" -f infra/compose.yml)

for service in postgres objectstore; do
  if [ -z "$("${COMPOSE[@]}" ps -q --status running "$service")" ]; then
    echo "ERROR: $service is not running. Run: make start-infra"
    exit 1
  fi
done

echo "== Free space on the disk holding the volumes =="
"${COMPOSE[@]}" exec -T postgres df -h /var/lib/postgresql/data

echo
echo "== Volumes =="
# Every volume on the host is listed by `docker system df -v`; keep this stack's.
docker system df -v --format '{{range .Volumes}}{{.Name}} {{.Size}}{{println}}{{end}}' \
  | awk 'BEGIN { printf "%-32s %s\n", "VOLUME", "SIZE" }
                $1 ~ /^jsa-(infra|app)_/ { printf "%-32s %s\n", $1, $2 }'

echo
echo "== Postgres: database size, then the 15 largest relations =="
echo "   (total = table + indexes + TOAST; rows are the planner's estimate)"
"${COMPOSE[@]}" exec -T -e PGPASSWORD="$POSTGRES_SUPERUSER_PASSWORD" postgres \
  psql -v ON_ERROR_STOP=1 -U "$POSTGRES_SUPERUSER" -d "$POSTGRES_DB" -P footer=off <<'SQL'
SELECT pg_size_pretty(pg_database_size(current_database())) AS database_size;

SELECT n.nspname || '.' || c.relname                  AS relation,
       pg_size_pretty(pg_total_relation_size(c.oid))  AS total,
       pg_size_pretty(pg_indexes_size(c.oid))         AS indexes,
       greatest(c.reltuples, 0)::bigint               AS approx_rows
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE c.relkind IN ('r', 'p', 'm')
   AND n.nspname NOT IN ('pg_catalog', 'information_schema')
 ORDER BY pg_total_relation_size(c.oid) DESC
 LIMIT 15;
SQL

echo "== Object storage, by bucket =="
"${COMPOSE[@]}" exec -T objectstore sh -c 'du -sh /data/* 2>/dev/null || echo "(no buckets)"'
