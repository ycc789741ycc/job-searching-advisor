# The SPA image.
#
# The built bundle carries no configuration: `docker-entrypoint.d` writes
# `config.js` from the environment at container start, so the same artifact is
# promoted through every environment (shared-context: Configuration — prefer
# run-time config over build-time inlining).
#
# `tools` is the Node image with dev dependencies, used by lint, typecheck,
# test-unit and gen-client so nobody installs Node on their machine.

# --- dependencies ----------------------------------------------------------
FROM node:22.23.2-bookworm-slim AS deps

WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci


# --- tools: lint, typecheck, unit tests, client generation -----------------
FROM deps AS tools

COPY . /app
# Vitest writes a transient config file into the working directory, so the
# directory itself must be writable by the unprivileged user. Not recursive:
# node_modules stays root-owned and read-only.
RUN chown node:node /app
USER node


# --- build -----------------------------------------------------------------
FROM deps AS build

COPY . /app
RUN npm run build


# --- runtime ---------------------------------------------------------------
# Unprivileged nginx: runs as uid 101, no root anywhere in the chain.
FROM nginxinc/nginx-unprivileged:1.31.6-alpine AS runtime

# uid 101 is the unprivileged `nginx` user this image runs as. The document
# root must be writable by it, because the entrypoint writes config.js there.
COPY --from=build --chown=101:101 /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --chmod=755 docker-entrypoint.d/10-write-config.sh /docker-entrypoint.d/10-write-config.sh

USER root
RUN chown 101:101 /usr/share/nginx/html
USER 101

EXPOSE 8080
