#!/usr/bin/env bash
# Blocks until every compose service reports healthy. Idempotent.
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE=(docker compose --env-file "${ENV_FILE:-.env}" -f infra/compose.yml)
deadline=$(( $(date +%s) + ${INFRA_HEALTH_TIMEOUT_SECONDS:-120} ))

while :; do
  unhealthy=0
  while read -r id; do
    [ -z "$id" ] && continue
    status=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id")
    name=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.service"}}' "$id")
    if [ "$status" != "healthy" ] && [ "$status" != "running" ]; then
      unhealthy=1
      echo "  $name: $status"
    elif [ "$status" != "healthy" ]; then
      unhealthy=1
      echo "  $name: $status (waiting for health check)"
    fi
  done < <("${COMPOSE[@]}" ps -q)

  [ "$unhealthy" -eq 0 ] && { echo "infra healthy"; exit 0; }
  [ "$(date +%s)" -ge "$deadline" ] && { echo "ERROR: infra did not become healthy in time"; exit 1; }
  sleep 2
done
