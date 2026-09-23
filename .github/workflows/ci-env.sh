#!/usr/bin/env bash
# Builds CI's .env from the committed template.
#
# The names come from .env.example, so a new required variable fails here until
# it is added in both places — which is the point.
set -euo pipefail

# Never clobber a developer's environment: this only ever creates a new one.
if [ -f .env ]; then
  echo "ERROR: .env already exists. This script only builds a fresh CI environment."
  exit 1
fi

key() { python3 -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())"; }
pw() { python3 -c "import secrets;print(secrets.token_urlsafe(18))"; }

SUPER_PW="$(pw)"; APP_PW="$(pw)"; CRAWLER_PW="$(pw)"; AGG_PW="$(pw)"; MIG_PW="$(pw)"

cp .env.example .env
set_value() { python3 - "$1" "$2" <<'PY'
import pathlib, sys
name, value = sys.argv[1], sys.argv[2]
path = pathlib.Path(".env")
lines = []
for line in path.read_text().splitlines():
    if line.split("=", 1)[0] == name and not line.strip().startswith("#"):
        lines.append(f"{name}={value}")
    else:
        lines.append(line)
path.write_text("\n".join(lines) + "\n")
PY
}

set_value APP_ENV ci
set_value CORS_ALLOWED_ORIGINS http://localhost:21471
# Service names on the container network, not localhost.
set_value POSTGRES_HOST postgres
set_value POSTGRES_PORT 5432
set_value POSTGRES_DB jsa
set_value POSTGRES_SUPERUSER postgres
set_value POSTGRES_SUPERUSER_PASSWORD "$SUPER_PW"
set_value APP_RW_PASSWORD "$APP_PW"
set_value CRAWLER_RW_PASSWORD "$CRAWLER_PW"
set_value AGGREGATOR_PASSWORD "$AGG_PW"
set_value MIGRATOR_PASSWORD "$MIG_PW"
set_value DATABASE_URL "postgresql+asyncpg://app_rw:${APP_PW}@postgres:5432/jsa"
set_value CRAWLER_DATABASE_URL "postgresql+asyncpg://crawler_rw:${CRAWLER_PW}@postgres:5432/jsa"
set_value MIGRATOR_DATABASE_URL "postgresql+psycopg://migrator:${MIG_PW}@postgres:5432/jsa"
set_value MASTER_ENCRYPTION_KEY "$(key)"
set_value AUTH_JWT_SECRET "$(pw)$(pw)"
set_value AUTH_COOKIE_SECURE false
set_value S3_ENDPOINT_URL http://objectstore:9000
set_value S3_PUBLIC_ENDPOINT_URL http://localhost:21473
set_value S3_REGION us-east-1
set_value S3_BUCKET jsa-ci
set_value S3_ACCESS_KEY_ID jsa-ci-access
set_value S3_SECRET_ACCESS_KEY "$(pw)"
set_value OAUTH_REDIRECT_BASE_URL http://localhost:21471
set_value GITHUB_OAUTH_CLIENT_ID ci-github
set_value GITHUB_OAUTH_CLIENT_SECRET "$(pw)"
set_value GITHUB_API_BASE_URL https://api.github.com
set_value JIRA_OAUTH_CLIENT_ID ci-jira
set_value JIRA_OAUTH_CLIENT_SECRET "$(pw)"
set_value JIRA_API_BASE_URL https://api.atlassian.com
set_value JIRA_OAUTH_BASE_URL https://auth.atlassian.com
set_value WEB_API_BASE_URL http://localhost:21470

blank=$(grep -E '^[A-Z_]+=$' .env || true)
if [ -n "$blank" ]; then
  echo "These variables from .env.example have no CI value yet:"
  echo "$blank"
  exit 1
fi
echo ".env built for CI"
