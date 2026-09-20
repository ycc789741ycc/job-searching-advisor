#!/usr/bin/env bash
# Stops one app process, idempotently. Never touches infra or data.
set -euo pipefail
cd "$(dirname "$0")/.."

name="$1"
pidfile=".local/run/$name.pid"
[ -f "$pidfile" ] || { echo "  $name not running"; exit 0; }

pid=$(cat "$pidfile")
if kill -0 "$pid" 2>/dev/null; then
  pkill -TERM -P "$pid" 2>/dev/null || true
  kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.5
  done
  kill -0 "$pid" 2>/dev/null && kill -KILL "$pid" 2>/dev/null || true
  echo "  $name stopped"
else
  echo "  $name not running"
fi
rm -f "$pidfile"
