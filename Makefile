# Standard targets required by design-guideline/ai-context/shared-context.md.
#
#   build-infra -> build-app -> start-infra -> [migrate] -> start-app
#   shutdown:    stop-app -> stop-infra
#
# Build never starts. Start never builds. Test neither builds nor starts.
# App targets never start infra. Every target is idempotent and fed from .env.
#
# Everything runs in a container. A contributor installs Docker and make, and
# nothing else — no Python, no Node, no psql, no linter. If you find yourself
# wanting to run a tool directly, a target is missing.

SHELL := /bin/bash
.DEFAULT_GOAL := help

ENV_FILE        ?= .env
INFRA_COMPOSE   := infra/compose.yml
APP_COMPOSE     := compose.app.yml
NETWORK         := jsa_net

COMPOSE_INFRA := docker compose --env-file $(ENV_FILE) -f $(INFRA_COMPOSE)
COMPOSE_APP   := docker compose --env-file $(ENV_FILE) -f $(APP_COMPOSE)

BACKEND_IMAGE       := jsa-backend:dev
BACKEND_TOOLS_IMAGE := jsa-backend-tools:dev
WEB_IMAGE           := jsa-web:dev
WEB_TOOLS_IMAGE     := jsa-web-tools:dev
SCANNER_IMAGE       := aquasec/trivy:0.74.0

# Hermetic: no network at all, so a unit test cannot reach infra by accident.
RUN_HERMETIC := docker run --rm --network none
# On the compose network, with configuration supplied at run time.
RUN_ON_NET   := docker run --rm --network $(NETWORK) --env-file $(ENV_FILE)

PATTERN ?=
ifdef PATTERN
PYTEST_FILTER := -k $(PATTERN)
VITEST_FILTER := -t $(PATTERN)
else
PYTEST_FILTER :=
VITEST_FILTER :=
endif

.PHONY: help require-env build-infra build-app start-infra start-app stop-app \
        stop-infra test-unit test-integration migrate lint typecheck scan \
        format gen-client lock reset-data logs

help:
	@echo "Standard targets:"
	@echo "  build-infra build-app start-infra start-app stop-app stop-infra"
	@echo "  test-unit test-integration"
	@echo "Gates (their own targets, never folded into a test target):"
	@echo "  lint typecheck scan"
	@echo "Supporting targets (never dependencies of the above):"
	@echo "  migrate format gen-client lock logs reset-data"

require-env:
	@test -f $(ENV_FILE) || { \
	  echo "ERROR: $(ENV_FILE) is missing. Copy .env.example to .env and fill it in."; \
	  exit 1; }

# --- build ------------------------------------------------------------------

build-infra: require-env
	$(COMPOSE_INFRA) pull

# Builds the images `start-app` runs, plus the `tools` layer on top of each that
# the test tiers and the gates run as one-off containers.
build-app: require-env
	$(COMPOSE_APP) build
	docker build --target tools -t $(BACKEND_TOOLS_IMAGE) backend
	docker build --target tools -t $(WEB_TOOLS_IMAGE) web
	docker pull $(SCANNER_IMAGE)

# --- start / stop -----------------------------------------------------------

start-infra: require-env
	$(COMPOSE_INFRA) up -d
	@echo "Waiting for infra to report healthy..."
	@infra/wait-for-healthy.sh
	@echo "Bootstrapping least-privilege database roles..."
	@infra/bootstrap-roles.sh

# start-app depends on migrate: pending migrations run to completion BEFORE any
# container serves traffic. A failed migration fails the start.
start-app: require-env migrate
	$(COMPOSE_APP) up -d
	@echo "api on port $$(grep -E '^API_PUBLISHED_PORT=' $(ENV_FILE) | cut -d= -f2)," \
	      "web on $$(grep -E '^WEB_PUBLISHED_PORT=' $(ENV_FILE) | cut -d= -f2)"

stop-app: require-env
	$(COMPOSE_APP) down --remove-orphans

# Preserves data on purpose. Use `make reset-data` to discard volumes.
stop-infra: require-env
	$(COMPOSE_INFRA) stop

logs: require-env
	$(COMPOSE_APP) logs --tail 100 -f

# --- migrations -------------------------------------------------------------

# Runs from the app image, as a one-off container, before anything serves.
migrate: require-env
	$(RUN_ON_NET) $(BACKEND_IMAGE) alembic -c alembic.ini upgrade head
	$(RUN_ON_NET) $(BACKEND_IMAGE) python -m app.apply_job_schema

# --- test -------------------------------------------------------------------

# Hermetic: no infra, no network, no running app. Must pass on a clean checkout.
test-unit:
	$(RUN_HERMETIC) $(BACKEND_TOOLS_IMAGE) pytest tests/unit $(PYTEST_FILTER)
	$(RUN_HERMETIC) $(WEB_TOOLS_IMAGE) npx vitest run $(VITEST_FILTER)

# Assumes infra is already up and migrated. Never starts infra itself.
test-integration: require-env
	$(RUN_ON_NET) $(BACKEND_TOOLS_IMAGE) pytest tests/integration $(PYTEST_FILTER)

# --- gates ------------------------------------------------------------------

lint:
	$(RUN_HERMETIC) $(BACKEND_TOOLS_IMAGE) ruff check .
	$(RUN_HERMETIC) $(BACKEND_TOOLS_IMAGE) ruff format --check .
	$(RUN_HERMETIC) $(BACKEND_TOOLS_IMAGE) lint-imports --config .importlinter \
	    --cache-dir /tmp/import-linter
	$(RUN_HERMETIC) $(WEB_TOOLS_IMAGE) npx eslint src

typecheck:
	$(RUN_HERMETIC) $(BACKEND_TOOLS_IMAGE) mypy .
	$(RUN_HERMETIC) $(WEB_TOOLS_IMAGE) npx tsc --noEmit

# Dependencies and the application image itself.
#
# pip-audit runs without --strict on purpose: torch is installed from the
# CPU-only wheel index, and its local version (`2.14.0+cpu`) has no PyPI entry
# to look up. Coverage for it comes from the image scan below, which reads the
# installed packages directly — so nothing is unscanned, and the strict flag is
# not quietly hiding a real advisory.
scan:
	docker run --rm $(BACKEND_TOOLS_IMAGE) pip-audit
	docker run --rm $(WEB_TOOLS_IMAGE) npm audit --audit-level=high
	docker run --rm -v /var/run/docker.sock:/var/run/docker.sock $(SCANNER_IMAGE) \
	    image --scanners vuln --severity HIGH,CRITICAL --exit-code 1 \
	    --ignore-unfixed $(BACKEND_IMAGE)

# --- supporting targets -----------------------------------------------------

# Applies formatting. Writes to source, so it mounts it — the `lint` gate that
# checks formatting does not.
format:
	docker run --rm --network none --user 0:0 -v $(PWD)/backend:/src -w /src \
	    -e RUFF_CACHE_DIR=/tmp/ruff $(BACKEND_TOOLS_IMAGE) ruff check --fix .
	docker run --rm --network none --user 0:0 -v $(PWD)/backend:/src -w /src \
	    -e RUFF_CACHE_DIR=/tmp/ruff $(BACKEND_TOOLS_IMAGE) ruff format .
	docker run --rm --network none --user 0:0 -v $(PWD)/web:/src -w /src \
	    $(WEB_TOOLS_IMAGE) npx prettier --write "src/**/*.{ts,tsx}" --log-level warn

# Regenerates the checked-in API client. The bind mount is how a generated file
# gets back onto the host; gates and tests never mount source.
gen-client: require-env
	$(RUN_ON_NET) $(BACKEND_IMAGE) python -m app.export_openapi > web/openapi.json
	docker run --rm --network none -v $(PWD)/web:/out -w /out $(WEB_TOOLS_IMAGE) \
	    npx openapi-typescript openapi.json -o src/api/schema.d.ts

# Regenerates backend/uv.lock after a dependency change. Like gen-client, this
# writes a generated file back to the host, which is why it mounts source.
# Needs the tools image, which carries the pinned uv — run `make build-app`
# first if it is not there yet. Root, because the lockfile is written back to a
# host-owned directory.
lock:
	docker run --rm --user 0:0 -v $(PWD)/backend:/work -w /work \
	    -e UV_PROJECT_ENVIRONMENT=/tmp/lockenv --entrypoint uv \
	    $(BACKEND_TOOLS_IMAGE) lock

# DESTRUCTIVE. Never a dependency of a build, start, stop or test target.
reset-data: require-env
	@read -p "This deletes all local infra volumes. Type 'yes' to continue: " ok; \
	 [ "$$ok" = "yes" ] || { echo "aborted"; exit 1; }
	$(COMPOSE_APP) down --remove-orphans
	$(COMPOSE_INFRA) down -v
