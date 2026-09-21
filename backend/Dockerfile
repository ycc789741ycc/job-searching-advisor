# The application image: one multi-stage Dockerfile, three images.
#
#   prod  production deps only, code baked in, non-root. What `make start-app`
#         runs by default, what `make scan` scans, and the only image CI or a
#         deployed environment ever uses.
#   test  prod plus the test dependencies. Both test tiers and every gate run
#         here, in either mode, never mounted.
#   dev   test plus dev tooling, run by `make start-app MODE=dev` with the
#         repo bind-mounted. Local only: never pushed, never deployed.
#
# `prod` is deliberately the LAST stage, so a bare `docker build` with no
# --target yields the production image and never the dev one.
#
# Every tag here is pinned. Configuration arrives at run time via --env-file,
# never baked in.

# --- dependencies ----------------------------------------------------------
FROM python:3.12.14-slim-bookworm AS deps

COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    VIRTUAL_ENV=/opt/venv \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /src

# Lockfile first: dependency layers survive a source change.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev


# --- base: the production contents -----------------------------------------
# Internal. `test` builds on it, and `prod` at the end of the file re-tags it.
FROM python:3.12.14-slim-bookworm AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    VIRTUAL_ENV=/opt/venv \
    # sentence-transformers caches models here; the volume is mounted for it.
    HF_HOME=/home/app/.cache/huggingface

# The model cache is created here, owned by app, because compose mounts the
# `modelcache` volume over it: Docker seeds an empty named volume with the
# ownership of the directory it lands on, and a mount point missing from the
# image is created root-owned — which the read-only, non-root worker can't write.
RUN groupadd --gid 10001 app \
 && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin app \
 && install -d -o app -g app /home/app/.cache /home/app/.cache/huggingface

COPY --from=deps /opt/venv /opt/venv

WORKDIR /app
COPY --chown=app:app . /app

# Caches go to /tmp, never into /app: the source tree stays untouched and the
# container needs no write access to it.
ENV RUFF_CACHE_DIR=/tmp/ruff \
    MYPY_CACHE_DIR=/tmp/mypy

USER app
EXPOSE 8000

# No default command: each service in compose names its own entrypoint, and
# one-off containers (migrate, tests, gates) name theirs.
CMD ["python", "-c", "print('specify a command')"]


# --- test: prod plus the test dependencies ---------------------------------
# Tests, lint, typecheck, import contracts and the dependency audit all run
# from here, so they exercise the same interpreter and the same source layout
# the application runs with.
FROM base AS test

USER root
COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /bin/uv

ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# --only-dev --inexact adds the dev group on top of the venv this stage
# inherited, instead of rewriting it — otherwise the layer duplicates every
# runtime dependency and the image doubles in size.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=/tmp/pyproject.toml \
    --mount=type=bind,source=uv.lock,target=/tmp/uv.lock \
    cd /tmp && uv sync --frozen --no-install-project --only-dev --inexact
# No recursive chown: the venv is world-readable and Python only reads from it.
# `chown -R` over a 1.5 GB tree would copy every file into this layer.

USER app


# --- dev: test plus dev tooling --------------------------------------------
# What `make start-app MODE=dev` runs, with the repo bind-mounted over /app by
# compose.dev.yaml. It carries the reloaders (watchfiles, uvicorn --reload) and
# the tools `make format` and `make lock` use (ruff, uv). Never pushed.
FROM test AS dev


# --- prod: production deps only, code baked in, non-root -------------------
# Last on purpose: the default target of a bare `docker build`.
FROM base AS prod
