# Job Searching Advisor

**Know where you stand, see which real jobs fit you, and close the gap to the
one you want.** Everything is built from the work you have actually done.

## The problem it solves

Looking for your next job usually means guessing. You don't know how your skills
compare to what the market is hiring for, which roles you could realistically
land, what it would take to reach the one you want, or how to present your work
for it. Your résumé undersells you, and advice from job boards is generic.

Job Searching Advisor answers those questions from evidence: your GitHub, your
Jira and your résumé, measured against real job openings.

```mermaid
flowchart LR
  WORK["📂 Your real work<br/>GitHub · Jira · résumé"] --> STAND["📊 Where you stand<br/>your skill strengths"]
  JOBS["🌐 Real job openings"] --> FIT["🎯 Which roles fit you<br/>fit · hiring bar · salary"]
  STAND --> FIT
  FIT -->|"you pick a target"| PLAN["🧭 How to get there<br/>a plan to close the gaps"]
  FIT -->|"you pick a target"| CV["📝 How to apply<br/>a résumé tailored to the role"]
  PLAN -. "new work makes you stronger" .-> WORK
```

Every claim it makes cites your own work, and all AI runs on **your own LLM
key**.

## What it does

| Feature | What you get |
|---|---|
| **Profile & evidence** | Connect GitHub and Jira, upload a résumé. Sources are parsed into evidence, with no AI involved. When the evidence is thin, the analyzer asks follow-up questions and adds your answers as evidence. |
| **Strength report** | A radar chart of 5–10 skill dimensions derived from *your* profile, not a fixed taxonomy. |
| **Role map** | A bubble chart of the roles closest to you in the real market. The x axis is the hiring bar, the y axis is salary and the bubble size is fit. You choose how many roles to analyse (3–20, [ADR 0003](docs/decisions/0003-let-the-user-choose-how-many-roles-to-analyse.md)). |
| **Gap plan** | Pick a **Target** (a matched opening, a watched role or a pasted JD) and get gaps ranked by the fit points each is worth, broken into milestones, tasks and projects. Plans are versioned per Target, and finished work carries forward. |
| **Resume Advisor** | A résumé written for a Target from cited evidence, with requirement coverage, in-place editing saved as versions, a streamed revision chat whose proposals apply only when you accept them, and PDF export. |
| **Accounts** | Email and password sign-in, or optional sign-in with Google. A write-only AI credential, plus a usage budget and ledger. |

Not built yet: suggesting a successor Target when a role splits, interview
reports (the hiring bar is estimated for now), email verification and password
reset, and linking or unlinking Google from Settings. See [`docs/plan.md`](docs/plan.md).

## How it is built

Design choices that are deliberate:

- **The crawler holds no secrets** and has no grant on any user schema. It
  emits events about companies and markets, and the worker fans those out to
  users.
- **Privacy is a storage location, not a flag.** Pasted JDs live in
  `market_user`, which the crawler's database role cannot reach.
- **Row-level security on every owner-zone table**, keyed on a per-transaction
  `app.user_id`. A forgotten `WHERE owner_id` returns nothing, not someone
  else's rows.
- **The AI credential is write-only.** Reading it back returns only the
  provider, the model and the last four characters.
- **Nothing reaches an LLM except through `kernel.ai_gateway`.** The gateway
  estimates cost, checks the budget, decrypts the key for exactly one call,
  validates the output against a schema and writes a ledger row.
- **Glassdoor, Indeed and LinkedIn are not crawled.** Market data comes from
  public ATS boards, schema.org JSON-LD career pages and JDs that users paste.

**Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 and Alembic on
Postgres. Procrastinate for jobs (no Redis). sentence-transformers and HDBSCAN
for local embedding and clustering. WeasyPrint for PDFs. React and Vite with an
`openapi-typescript` client generated from the API. Details are in
[`docs/technical_boundaries.md`](docs/technical_boundaries.md).

## Getting started

You need **Docker** and **`make`**, and nothing else. Every toolchain, database,
linter and migration runs in a container.

```sh
cp .env.example .env      # fill in every blank
make build-infra          # pull the pinned Postgres and MinIO images
make build-app            # build the prod images, plus the test images the gates use
make start-infra          # start infra, wait until healthy, create least-privilege DB roles
make start-app            # run migrations to completion, then start api, worker, crawler and web
```

Open **http://localhost:21471**. The host ports are this repo's block:

| Port | Service |
|---|---|
| `21470` | api |
| `21471` | web |
| `21472` | Postgres |
| `21473` | MinIO |
| `21474` | MinIO console |

To stop, run `make stop-app` and then `make stop-infra`. `stop-infra` keeps your
data. Only `make clean-up-infra` deletes it.

### Developing with live source

```sh
make build-app MODE=dev   # once, and again after a dependency change
make start-app MODE=dev
```

This bind-mounts `backend/` and `web/src` read-only. When you save a file, the
api, the worker and the SPA (through Vite HMR) reload within a couple of
seconds. The crawler does not reload, because it would hit real job boards on
every save. `MODE` defaults to `prod`, which has nothing mounted and is the only
mode CI and deployed environments use.

## Tests and quality gates

```sh
make test-unit                   # hermetic: runs with --network none
make test-integration            # needs `make start-infra` first
make test-unit PATTERN=rolemap   # narrow either tier
make lint
make typecheck
make scan                        # Python and npm dependencies, plus the prod images (Trivy)
```

Supporting targets, which are never dependencies of the targets above:
`migrate`, `format`, `gen-client` (regenerates the TypeScript API client),
`lock` (regenerates `backend/uv.lock`), `logs`, `stats` (CPU, memory and
restarts per container, against its limit), `disk-usage` (free disk, volumes,
the largest tables, buckets), `clean-up-cache` (deletes tool caches and build
output, all regenerated on the next run) and `clean-up-infra`, which is the
only destructive one.

## Repository layout

```
backend/
  src/
    api/      FastAPI app and one router per component
    worker/   queue worker and outbox dispatcher
    crawler/  its own deployable: the crawl loop, no secrets
    cli/      migrate, seed, OpenAPI export
    wiring/   composition root shared by every deployable
    kernel/   technical kernel with no domain logic: db, outbox, jobs, auth, crypto,
              storage, ai_gateway, fetch, embeddings
    advisor/  identity · profile · market · rolemap · assessment · target · gapplan · resume
                __init__.py  the only importable surface; everything _-prefixed is private
                _service.py use cases · _domain/ pure rules · _infra/ models and adapters
  migrations/ Alembic
  tests/      unit/ and integration/, each mirroring src/
web/          React + Vite SPA on the prototype's design system (ADR 0004)
infra/        infra compose project, DB role bootstrap, health wait
prototype/    the original clickable prototype
docs/         intent, domain model, technical boundaries, plan, decisions
```

Sixteen `import-linter` contracts in `backend/.importlinter` enforce the module
boundaries in CI. If one of them breaks, the design is wrong, not the contract.

## Documentation

| Document | What it covers |
|---|---|
| [`docs/intent.md`](docs/intent.md) | What the product is for |
| [`docs/domain_model_review.md`](docs/domain_model_review.md) | The domain model, bounded contexts and the decisions behind them |
| [`docs/technical_boundaries.md`](docs/technical_boundaries.md) | Deployables, module boundaries, data and trust boundaries, and the AI gateway |
| [`docs/plan.md`](docs/plan.md) | Scope for phases 1, 2 and 3 |
| [`docs/decisions/`](docs/decisions/README.md) | Decision records for choices that are costly to reverse |
