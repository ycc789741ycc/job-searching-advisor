#!/usr/bin/env bash
# Runs a command with .env loaded. The single place the environment is read
# into a process, so no target grows its own copy of this.
set -euo pipefail
cd "$(dirname "$0")/.."

env_file="${ENV_FILE:-.env}"
[ -f "$env_file" ] || { echo "ERROR: $env_file is missing."; exit 1; }
set -a; . "./$env_file"; set +a
exec "$@"
