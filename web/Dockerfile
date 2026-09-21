# The SPA image.
#
# The built bundle carries no configuration: `docker-entrypoint.d` writes
# `config.js` from the environment at container start, so the same artifact is
# promoted through every environment (shared-context: Configuration — prefer
# run-time config over build-time inlining).
#
# Three images from this one file:
#
#   prod  nginx serving the built bundle, non-root. The default, and the only
#         image CI or a deployed environment uses. Last stage on purpose.
#   test  Node with every dependency and the source: lint, typecheck,
#         test-unit and gen-client run here, never mounted. The SPA's
#         production artifact is static files, so "prod plus test deps" means
#         the source `build` compiles, with the tools that check it.
#   dev   test plus the Vite dev server, run by `make start-app MODE=dev` with
#         web/src bind-mounted. Local only: never pushed, never deployed.

# --- dependencies ----------------------------------------------------------
FROM node:22.23.2-bookworm-slim AS deps

WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci


# --- test: lint, typecheck, unit tests, client generation ------------------
FROM deps AS test

COPY . /app
# Vitest writes a transient config file into the working directory, so the
# directory itself must be writable by the unprivileged user. Not recursive:
# node_modules stays root-owned and read-only.
RUN chown node:node /app
USER node


# --- dev: the Vite dev server with hot module replacement -----------------
# Listens on 8080, the port the prod image uses, so compose's published port
# mapping applies unchanged in either mode.
FROM test AS dev

CMD ["npx", "vite", "--host", "0.0.0.0", "--port", "8080", "--strictPort"]


# --- build -----------------------------------------------------------------
FROM deps AS build

COPY . /app
RUN npm run build


# --- prod ------------------------------------------------------------------
# Unprivileged nginx: runs as uid 101, no root anywhere in the chain.
FROM nginxinc/nginx-unprivileged:1.31.6-alpine AS prod

# uid 101 is the unprivileged `nginx` user this image runs as. The document
# root must be writable by it, because the entrypoint writes config.js there.
COPY --from=build --chown=101:101 /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --chmod=755 docker-entrypoint.d/10-write-config.sh /docker-entrypoint.d/10-write-config.sh

USER root
RUN chown 101:101 /usr/share/nginx/html
USER 101

EXPOSE 8080
