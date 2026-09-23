# Job Searching Advisor

Turns the work someone has actually done — GitHub, Jira, their résumé — into a
picture of where they stand (a skill radar) and what is worth aiming at (a role
map of real openings), with every claim traceable to evidence.

All AI runs on **the user's own provider key**. The platform runs only the work
that needs no model: crawling, parsing, embedding, clustering.

## Read these first

| Document | What it settles |
|---|---|
| `docs/intent.md` | What the product is for |
| `docs/domain_model_review.md` | The domain model, bounded contexts and the 14 decisions behind them |
| `docs/technical_boundaries.md` | Deployables, module boundaries, data and trust boundaries, the AI gateway |
| `docs/plan.md` | Phase 1 / 2 / 3 scope |
| `docs/decisions/` | Decision records for choices that are costly to reverse |

The design guideline at `/Users/yoshi/repo/design-guideline` applies here too.

## Running it

Everything runs in a container. Install Docker and `make` — nothing else. There
is no Python, Node, `psql`, linter or migration CLI to put on your machine, and
a bare `npm`/`pip`/`pytest`/`alembic` anywhere in this repo means a target is
missing.

```
cp .env.example .env      # fill in every blank; nothing has a default that matters
make build-infra          # pull the pinned Postgres and MinIO images
make build-app            # build the prod images, plus the test images the gates use
make start-infra          # compose up, wait healthy, then the least-privilege DB roles
make start-app            # runs migrations to completion first, then api/worker/crawler/web
```

`build-app`, `start-app` and `stop-app` take `MODE=dev|prod`, default `prod`;
any other value fails. Each Dockerfile has three stages, each with its own tag:

| Stage | Tag | Used by |
|---|---|---|
| `prod` | `jsa-*:prod` | `MODE=prod`: `compose.yaml` alone, nothing mounted. The only image CI or a deployed environment uses, and the one `scan` scans. |
| `test` | `jsa-*:test` | Both test tiers and every gate, in either mode, never mounted. `build-app` builds it whichever mode you ask for. |
| `dev` | `jsa-*:dev` | `MODE=dev`: `compose.yaml` + `compose.dev.yaml`, with the repo bind-mounted. Local only — never pushed, never deployed. |

`start-app` never builds: if the image for the mode is missing it stops and tells
you which `make build-app` to run. Both modes migrate first. Only one mode runs at
a time — starting one replaces the other — and `stop-app` stops whichever is
running. The app itself never reads `MODE`.

### Developing with live source

```
make build-app MODE=dev   # once, and again after a dependency change
make start-app MODE=dev
```

Layers `compose.dev.yaml` on `compose.yaml`: your checkout's `backend/` and
`web/src` are bind-mounted read-only, and saving a file reloads what uses it —
the api through uvicorn's reloader, the worker through `watchfiles`, and the SPA
through the Vite dev server with hot module replacement, on the same port. A
save typically shows up within a couple of seconds.

- The **crawler** is mounted but does not reload, because it crawls as soon as
  it starts and would hit real job boards on every save. Restart it with
  `make stop-app && make start-app MODE=dev`.
- Changing **dependencies**, `vite.config.ts` or `package.json` needs
  `make build-app MODE=dev` — those live in the image, not the mount.
- In dev, `migrate` (which `start-app` runs first) sees the mounted source, so a
  migration you have just written applies without a rebuild.

Every source mount in the repo lives in `compose.dev.yaml` and nowhere else — never
as `-v` in a Makefile recipe. The overlay is deliberately not called
`compose.override.yaml`, because compose would merge that into prod automatically.

Hostnames in `.env` are compose service names on the `jsa_net` network, not
`localhost`. The only host-facing values are the `*_PUBLISHED_PORT` numbers,
which are what your browser and any database client connect to. They take this
repo's block, `21470`–`21474` (api, web, Postgres, MinIO, MinIO console), never a
common default like `8000`, `5173` or `5432`, so the stack runs beside other
projects without a bind failure. Containers keep their conventional ports inside
`jsa_net`.

`make test-unit` runs in a container with `--network none`, so it is hermetic by
construction rather than by convention. `make test-integration` runs on the
compose network and assumes infra is up and migrated — it tells you to run
`make start-infra` if it is not. Narrow either with `PATTERN=`.

`make lint`, `make typecheck` and `make scan` are their own gates, never folded
into a test target. `scan` covers Python dependencies, npm dependencies, and the
prod images themselves. It hands each image to Trivy as a `docker save` stream,
rather than mounting the Docker socket, which would give the scanner root on the
host.

Supporting targets, never dependencies of the above: `migrate`, `format`,
`gen-client`, `lock` (regenerates `backend/uv.lock` after a dependency change),
`logs`, and `clean-up-infra` (the only destructive one).

- `format` and `lock` write to source, so they run through `compose.dev.yaml`,
  where the mounts live. They need the dev images (`make build-app MODE=dev`),
  and they run as your own uid, so the files they rewrite stay yours.
- `gen-client` mounts nothing. The OpenAPI document leaves one container on
  stdout and enters the next on stdin, so it runs from the test images and works
  in CI. Prettier is told not to touch the generated `schema.d.ts`; otherwise
  `format` and `gen-client` would keep rewriting each other's output.

Infra and the app are separate compose projects (`jsa-infra`, `jsa-app`) sharing
the `jsa_net` network, so an app target can never remove an infra container. App
images carry `pull_policy: never`: they are built locally, and a missing one
should fail rather than send compose to Docker Hub for a stranger's image of the
same name.

Base and tool images are pinned by version — never `latest` — in the
`Dockerfile`s and compose files. Configuration arrives at run time through
`--env-file`, so `build-app` produces one prod artifact that is promoted
unchanged; the SPA gets its settings from
a `config.js` the container writes at start, which is why there are no `VITE_`
variables.

## Shape of the code

```
backend/
  app/        composition root: FastAPI app, worker and crawler entrypoints, queue wiring
  kernel/     technical kernel, no domain: db, outbox, jobs, auth, crypto, storage,
              ai_gateway, fetch, embeddings
  domain/     the domain model, one package per feature: identity · profile · market ·
              rolemap · assessment · target · gapplan · resume. Pure rules, no
              I/O, no framework, no kernel.
  modules/    identity · profile · market · rolemap · assessment · target ·
              gapplan · resume
                public.py   the ONLY importable surface
                api.py      FastAPI routers
                infra/      repositories and adapters
                jobs.py     worker handlers
  crawler/    its own deployable: hostile HTML, no secrets, no user data
web/          React + Vite SPA, on the prototype's Organic design system (ADR 0004)
```

The domain model sits in one top-level `domain/` folder rather than inside each
module, as the design guideline requires (its ADR 0002). `modules/<m>` uses only
`domain/<m>`; another module's rules are reached through that module's
`public.py`. Domain feature packages never import each other.

Sixteen `import-linter` contracts in `backend/.importlinter` enforce those boundaries, and
they run in CI. If one breaks, the design is wrong, not the contract.

## Things that are deliberate

- **The crawler holds no secrets and has no grant on any user schema.** It emits
  events about companies and markets; the worker's dispatcher resolves those to
  users. That fan-out is the only cross-user read, and it has its own narrow
  SELECT-only policy.
- **Privacy is a storage location, not a flag.** Pasted JDs live in
  `market_user.private_job_posting`, which the crawler role physically cannot
  reach.
- **Row-level security on every owner-zone table**, keyed on a per-transaction
  `app.user_id`. Forgetting a `WHERE owner_id` returns nothing, not someone
  else's rows.
- **We run our own sign-in.** Argon2id passwords, 15-minute access tokens
  held only in memory, and rotating refresh tokens in an httpOnly
  `SameSite=Strict` cookie stored hashed. A reused refresh token revokes its
  whole chain. There is no address verification or password reset yet — both
  wait on email delivery. Why, and what it costs: `docs/decisions/0001`.
- **The AI credential is write-only.** It can be set, tested, replaced or
  deleted; a read returns provider, model and the last four characters.
- **Nothing reaches an LLM except through `kernel.ai_gateway`**, which estimates
  cost, checks the budget, decrypts the key for exactly one call, validates the
  output against a Pydantic schema, and writes a ledger row.
- **AI output is untrusted.** Evidence ids it cites must exist in *that user's*
  profile or the whole response is rejected — that is the guard against invented
  claims.
- **Glassdoor, Indeed and LinkedIn are not crawled** (domain decision 6). Market
  data comes from public ATS job boards, schema.org JSON-LD career pages, and
  JDs users paste themselves.

## Phase 1 scope

In: accounts, GitHub and Jira connectors, résumé upload, LLM configuration,
market data from ATS boards and pasted JDs, the strength report, the role map,
and follow-up questions.

## Phase 2 scope

In: the gap plan — plan a route to a Target (a matched opening, a watched role
or a pasted JD), with gaps ranked by the fit points each is worth, milestones,
tasks and projects drafted on the user's key, versions per Target with finished
work carried forward, and plan history. `target` resolves what a plan aims at
and has no tables (ADR 0005). Drafting is a job whose row the page polls
(ADR 0006).

And the Resume Advisor: a résumé written for a Target from cited evidence, over
the uploaded résumé when there is one, with requirement coverage decided by
scores; in-place editing saved as versions; a revision chat streamed over SSE
whose proposals apply only on request; and PDF export on the worker's `docs`
queue with WeasyPrint (ADR 0007). Its routes are `/tailored-resumes` —
`/resumes` is the profile's upload endpoint.

Not yet: suggesting a successor Target when a Role splits (rolemap does not
emit `RoleSplitOrMerged` yet), and the interview-report prompt after a résumé
is tailored. The hiring bar is `estimated` only — `InterviewReport`
arrives with the reporting flow later. Google login is Phase 3, as our own
OAuth exchange that issues our own session token.
