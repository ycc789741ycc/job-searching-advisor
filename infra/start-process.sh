#!/usr/bin/env bash
# Starts one app process in the background, idempotently.
# Usage: start-process.sh <name> <command...>
set -euo pipefail
cd "$(dirname "$0")/.."

name="$1"; shift
cmd="$*"
run_dir=".local/run"; log_dir=".local/log"
mkdir -p "$run_dir" "$log_dir"
pidfile="$run_dir/$name.pid"

if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
  echo "  $name already running (pid $(cat "$pidfile"))"
  exit 0
fi

set -a; . ./"${ENV_FILE:-.env}"; set +a
nohup bash -c "$cmd" >>"$log_dir/$name.log" 2>&1 &
echo $! > "$pidfile"
echo "  $name started (pid $(cat "$pidfile"))"
