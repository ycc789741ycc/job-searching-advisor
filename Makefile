# Standard targets required by design-guideline/ai-context/shared-context.md.
#
#   build-infra -> build-app -> start-infra -> [migrate] -> start-app
#   shutdown:    stop-app -> stop-infra
#
# Build never starts. Start never builds. Test neither builds nor starts.
# App targets never start infra. Every target is idempotent and fed from .env.

SHELL := /bin/bash
.DEFAULT_GOAL := help

ENV_FILE      ?= .env
COMPOSE_FILE  := infra/compose.yml
COMPOSE       := docker compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE)
RUN_DIR       := .local/run
LOG_DIR       := .local/log
UV            := uv
WITH_ENV      := infra/with-env.sh
UV_RUN        := $(UV) run --directory backend
PATTERN       ?=

# Narrowing: `make test-unit PATTERN=assessment`
ifdef PATTERN
PYTEST_FILTER := -k $(PATTERN)
else
PYTEST_FILTER :=
endif

.PHONY: help require-env build-infra build-app start-infra start-app stop-app \
        stop-infra test-unit test-integration migrate lint scan gen-client reset-data

help:
	@echo "Standard targets:"
	@echo "  build-infra build-app start-infra start-app stop-app stop-infra"
	@echo "  test-unit test-integration"
	@echo "Supporting targets (never dependencies of the above):"
	@echo "  migrate lint scan gen-client reset-data"

require-env:
	@test -f $(ENV_FILE) || { \
	  echo "ERROR: $(ENV_FILE) is missing. Copy .env.example to .env and fill it in."; \
	  exit 1; }

# --- build ------------------------------------------------------------------

build-infra: require-env
	$(COMPOSE) pull
	$(COMPOSE) build

build-app:
	$(UV) sync --directory backend
	cd web && npm ci && npm run build

# --- start / stop -----------------------------------------------------------

start-infra: require-env
	$(COMPOSE) up -d
	@echo "Waiting for infra to report healthy..."
	@infra/wait-for-healthy.sh
	@echo "Bootstrapping least-privilege database roles..."
	@infra/bootstrap-roles.sh

# start-app depends on migrate: pending migrations run to completion BEFORE any
# process serves traffic. A failed migration fails the start.
start-app: require-env migrate
	@mkdir -p $(RUN_DIR) $(LOG_DIR)
	@infra/start-process.sh api    "$(UV_RUN) uvicorn app.api_main:app --host 0.0.0.0 --port $${PORT:-8000}"
	@infra/start-process.sh worker "$(UV_RUN) python -m app.worker_main"
	@infra/start-process.sh crawler "$(UV_RUN) python -m app.crawler_main"
	@echo "app started; logs in $(LOG_DIR)"

stop-app:
	@infra/stop-process.sh crawler
	@infra/stop-process.sh worker
	@infra/stop-process.sh api
	@echo "app stopped"

# Preserves data on purpose. Use `make reset-data` to discard volumes.
stop-infra: require-env
	$(COMPOSE) stop

# --- migrations -------------------------------------------------------------

migrate: require-env
	$(WITH_ENV) $(UV_RUN) alembic -c alembic.ini upgrade head
	$(WITH_ENV) $(UV_RUN) python -m app.apply_job_schema

# --- test -------------------------------------------------------------------

# Hermetic: no infra, no network, no running app. Must pass on a clean checkout.
test-unit:
	$(UV_RUN) pytest tests/unit $(PYTEST_FILTER)
	cd web && npm run test:unit

# Assumes infra is already up and migrated. Never starts infra itself.
test-integration: require-env
	$(WITH_ENV) $(UV_RUN) pytest tests/integration $(PYTEST_FILTER)

# --- supporting targets -----------------------------------------------------

lint:
	$(UV_RUN) ruff check .
	$(UV_RUN) ruff format --check .
	$(UV_RUN) mypy .
	$(UV_RUN) lint-imports --config ../.importlinter
	cd web && npm run lint && npm run typecheck

scan:
	$(UV_RUN) pip-audit
	cd web && npm audit --audit-level=high

gen-client: require-env
	$(WITH_ENV) $(UV_RUN) python -m app.export_openapi > web/openapi.json
	cd web && npm run gen:client

# DESTRUCTIVE. Never a dependency of a build, start, stop or test target.
reset-data: require-env
	@read -p "This deletes all local infra volumes. Type 'yes' to continue: " ok; \
	 [ "$$ok" = "yes" ] || { echo "aborted"; exit 1; }
	$(COMPOSE) down -v
