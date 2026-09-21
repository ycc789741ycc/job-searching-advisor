# The application image.
#
# `runtime` is what `start-app` runs and what gets promoted between
# environments unchanged. `tools` is that same image plus the dev dependencies,
# and it is what the test tiers and the gates run as one-off containers — so a
# contributor never installs Python, uv, a linter or a migration CLI on their
# machine.
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


# --- runtime: the app image ------------------------------------------------
FROM python:3.12.14-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    VIRTUAL_ENV=/opt/venv \
    # sentence-transformers caches models here; the volume is mounted for it.
    HF_HOME=/home/app/.cache/huggingface

RUN groupadd --gid 10001 app \
 && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin app

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


# --- tools: the app image plus dev dependencies ----------------------------
# Tests, lint, typecheck, import contracts and the dependency audit all run
# from here, so they exercise the same interpreter and the same source layout
# the application runs with.
FROM runtime AS tools

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
