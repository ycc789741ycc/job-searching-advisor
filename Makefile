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
#
# Modes. `build-app`, `start-app` and `stop-app` take MODE=dev|prod, default
# prod; anything else fails.
#   prod  the `prod` stage, compose.yaml alone, nothing mounted. What CI and
#         every deployed environment use, and what `scan` scans.
#   dev   the `dev` stage, compose.yaml + compose.dev.yaml: the repo
#         bind-mounted, reloading on save. Local only.
# Tests and gates ignore MODE: they always run the `test` stage, never mounted,
# which `build-app` builds in either mode. The app itself never reads MODE.

SHELL := /bin/bash
.DEFAULT_GOAL := help

ENV_FILE      ?= .env
INFRA_COMPOSE := infra/compose.yml
NETWORK       := jsa_net

MODE ?= prod

COMPOSE_BASE := docker compose --env-file $(ENV_FILE) -f compose.yaml
COMPOSE_DEV  := $(COMPOSE_BASE) -f compose.dev.yaml
ifeq ($(MODE),dev)
COMPOSE_APP  := $(COMPOSE_DEV)
else
COMPOSE_APP  := $(COMPOSE_BASE)
endif
COMPOSE_INFRA := docker compose --env-file $(ENV_FILE) -f $(INFRA_COMPOSE)

# One tag per mode, plus the test image both modes build.
MODE_IMAGES        := jsa-backend:$(MODE) jsa-web:$(MODE)
PROD_IMAGES        := jsa-backend:prod jsa-web:prod
BACKEND_TEST_IMAGE := jsa-backend:test
WEB_TEST_IMAGE     := jsa-web:test
SCANNER_IMAGE      := aquasec/trivy:0.74.0

# The dev overlay's source-writing tools run as the invoking user, so the files
# they rewrite stay owned by that user on every host.
export HOST_UID := $(shell id -u)
export HOST_GID := $(shell id -g)

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

.PHONY: help require-env check-mode require-mode-images build-infra build-app \
        start-infra start-app stop-app stop-infra test-unit test-integration \
        migrate lint typecheck scan format gen-client lock clean-up-infra logs

help:
	@echo "Standard targets (build-app, start-app, stop-app take MODE=dev|prod):"
	@echo "  build-infra build-app start-infra start-app stop-app stop-infra"
	@echo "  test-unit test-integration"
	@echo "Gates (their own targets, never folded into a test target):"
	@echo "  lint typecheck scan"
	@echo "Supporting targets (never dependencies of the above):"
	@echo "  migrate format gen-client lock logs clean-up-infra"

require-env:
	@test -f $(ENV_FILE) || { \
	  echo "ERROR: $(ENV_FILE) is missing. Copy .env.example to .env and fill it in."; \
	  exit 1; }

check-mode:
	@case "$(MODE)" in dev|prod) ;; \
	  *) echo "ERROR: MODE must be dev or prod, got '$(MODE)'."; exit 1 ;; esac

# Start never builds: it fails here, with the command to run, when the image
# for the requested mode is missing.
require-mode-images: check-mode
	@for image in $(MODE_IMAGES); do \
	  docker image inspect $$image >/dev/null 2>&1 || { \
	    echo "ERROR: $$image is missing. Run: make build-app MODE=$(MODE)"; exit 1; }; \
	done

# --- build ------------------------------------------------------------------

build-infra: require-env
	$(COMPOSE_INFRA) pull

# The images for the requested mode, plus the `test` stage the test tiers and
# gates run in — built whichever mode was asked for.
build-app: require-env check-mode
	$(COMPOSE_APP) build
	docker build --target test -t $(BACKEND_TEST_IMAGE) backend
	docker build --target test -t $(WEB_TEST_IMAGE) web
	docker pull $(SCANNER_IMAGE)

# --- start / stop -----------------------------------------------------------

start-infra: require-env
	$(COMPOSE_INFRA) up -d
	@echo "Waiting for infra to report healthy..."
	@infra/wait-for-healthy.sh
	@echo "Bootstrapping least-privilege database roles..."
	@infra/bootstrap-roles.sh

# Both modes migrate first: pending migrations run to completion BEFORE any
# container serves traffic, and a failed migration fails the start. Starting
# one mode replaces the other, since both run the same services.
start-app: require-env require-mode-images migrate
	$(COMPOSE_APP) up -d --no-build
	@echo "MODE=$(MODE): api on $$($(COMPOSE_APP) port api 8000)," \
	      "web on $$($(COMPOSE_APP) port web 8080)"

# Stops whichever mode is running: both run the same services in one project.
stop-app: require-env check-mode
	$(COMPOSE_BASE) down --remove-orphans

# Preserves data on purpose. Use `make clean-up-infra` to discard volumes.
stop-infra: require-env
	$(COMPOSE_INFRA) stop

logs: require-env
	$(COMPOSE_BASE) logs --tail 100 -f

# --- migrations -------------------------------------------------------------

# A one-off container from the mode's own image. In dev it sees the mounted
# source, so a migration written a moment ago applies without a rebuild.
migrate: require-env require-mode-images
	$(COMPOSE_APP) run --rm migrate

# --- test -------------------------------------------------------------------

# Hermetic: no infra, no network, no running app. Must pass on a clean checkout.
test-unit:
	$(RUN_HERMETIC) $(BACKEND_TEST_IMAGE) pytest tests/unit $(PYTEST_FILTER)
	$(RUN_HERMETIC) $(WEB_TEST_IMAGE) npx vitest run $(VITEST_FILTER)

# Assumes infra is already up and migrated. Never starts infra itself.
test-integration: require-env
	$(RUN_ON_NET) $(BACKEND_TEST_IMAGE) pytest tests/integration $(PYTEST_FILTER)

# --- gates ------------------------------------------------------------------

lint:
	$(RUN_HERMETIC) $(BACKEND_TEST_IMAGE) ruff check .
	$(RUN_HERMETIC) $(BACKEND_TEST_IMAGE) ruff format --check .
	$(RUN_HERMETIC) $(BACKEND_TEST_IMAGE) lint-imports --config .importlinter \
	    --cache-dir /tmp/import-linter
	$(RUN_HERMETIC) $(WEB_TEST_IMAGE) npx eslint src

# web/tsconfig.json lists no files, only a reference to tsconfig.app.json, so a
# bare `tsc --noEmit` there checks nothing. Name the project that holds src/.
typecheck:
	$(RUN_HERMETIC) $(BACKEND_TEST_IMAGE) mypy .
	$(RUN_HERMETIC) $(WEB_TEST_IMAGE) npx tsc -p tsconfig.app.json --noEmit

# Dependencies, and the prod images themselves: prod is what gets promoted, so
# prod is what gets scanned.
#
# The images reach Trivy as a `docker save` stream on stdin rather than by
# mounting the Docker socket, which would hand the scanner root on the host.
#
# pip-audit runs without --strict on purpose: torch is installed from the
# CPU-only wheel index, and its local version (`2.14.0+cpu`) has no PyPI entry
# to look up. Coverage for it comes from the image scan below, which reads the
# installed packages directly — so nothing is unscanned, and the strict flag is
# not quietly hiding a real advisory.
scan:
	@for image in $(PROD_IMAGES); do \
	  docker image inspect $$image >/dev/null 2>&1 || { \
	    echo "ERROR: $$image is missing; scan covers the prod images. Run: make build-app"; exit 1; }; \
	done
	docker run --rm $(BACKEND_TEST_IMAGE) pip-audit
	docker run --rm $(WEB_TEST_IMAGE) npm audit --audit-level=high
	@for image in $(PROD_IMAGES); do \
	  echo "trivy: $$image"; \
	  docker save $$image | docker run --rm -i --entrypoint sh $(SCANNER_IMAGE) -c \
	    'cat > /tmp/image.tar && trivy image --quiet --input /tmp/image.tar \
	       --scanners vuln --severity HIGH,CRITICAL --exit-code 1 --ignore-unfixed' \
	    || exit 1; \
	done

# --- supporting targets -----------------------------------------------------

# Applies formatting. It writes to source, so it runs through the dev overlay,
# where every source mount lives; the `lint` gate that checks formatting never
# mounts anything. Needs the dev images: `make build-app MODE=dev`.
format: require-env
	@$(MAKE) --no-print-directory require-mode-images MODE=dev
	$(COMPOSE_DEV) run --rm backend-tools sh -c 'ruff check --fix . && ruff format .'
	$(COMPOSE_DEV) run --rm web-tools npx prettier --write "src/**/*.{ts,tsx}" --log-level warn

# Regenerates the checked-in API client from the API's OpenAPI document.
# Mount-free: the document leaves one container on stdout and enters the next
# on stdin, so it runs from the test images and works in CI.
gen-client: require-env
	$(RUN_HERMETIC) --env-file $(ENV_FILE) $(BACKEND_TEST_IMAGE) \
	    python -m app.export_openapi > web/openapi.json
	$(RUN_HERMETIC) -i $(WEB_TEST_IMAGE) sh -c \
	    'cat > /tmp/openapi.json && npx openapi-typescript /tmp/openapi.json -o /tmp/schema.d.ts >&2 && cat /tmp/schema.d.ts' \
	    < web/openapi.json > web/src/api/schema.d.ts.tmp \
	  && mv web/src/api/schema.d.ts.tmp web/src/api/schema.d.ts \
	  || { rm -f web/src/api/schema.d.ts.tmp; exit 1; }

# Regenerates backend/uv.lock after a dependency change. It writes to source,
# so it runs through the dev overlay. Needs the dev images: `make build-app MODE=dev`.
lock: require-env
	@$(MAKE) --no-print-directory require-mode-images MODE=dev
	$(COMPOSE_DEV) run --rm backend-tools uv lock

# DESTRUCTIVE. Never a dependency of a build, start, stop or test target.
clean-up-infra: require-env
	@read -p "This deletes all local infra volumes. Type 'yes' to continue: " ok; \
	 [ "$$ok" = "yes" ] || { echo "aborted"; exit 1; }
	$(COMPOSE_BASE) down --remove-orphans
	$(COMPOSE_INFRA) down -v
