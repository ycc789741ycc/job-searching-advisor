# 0009. Package the backend by component

**Status:** Accepted — 2026-09-27.

## Context

The backend followed the design guideline's ADR 0002: the domain model in one
top-level `domain/` folder, with each feature split across `domain/<m>/` and
`modules/<m>/{public,api,jobs,infra}`, plus `app/` for the composition root and
entrypoints, `kernel/`, and `crawler/`. The guideline has since replaced that
rule with *package by component* (its ADR 0003). Backend source now holds
delivery mechanisms (`api/`, `worker/`, `cli/`) and one application package
named after the product. That package splits into components, each owning its
domain model, use cases and data access, and each exposing them only through its
`__init__.py`.

Under the old layout, one capability spread across three top-level folders.
`modules.market.jobs` imported `crawler.*` and `app.container`, an inner package
reaching out to the ones that wire it. The worker's dispatcher ran raw SQL
against `market_user` tables it did not own.

## Decision

```
backend/src/
  api/        FastAPI: main.py, dependencies, error envelope, routes/<component>.py
  worker/     queue worker entrypoint and the outbox dispatcher
  crawler/    crawler entrypoint: the loop only
  cli/        migrate, job-queue schema, baseline seed, OpenAPI export
  wiring/     composition root: container.py, crawl.py, queue.py, models.py
  kernel/     technical kernel, unchanged
  advisor/    the application: identity · profile · market · rolemap ·
              assessment · target · gapplan · resume
backend/tests/{unit,integration}/   each mirrors src/
```

- **A component** is `advisor/<c>/`. Its `__init__.py` is its public API.
  `service.py` holds its use cases, `domain/` its pure rules, `infra/` its
  ORM models, repositories and adapters, and `jobs.py` the use cases the worker
  runs. Those submodules are private. One import-linter contract per
  component forbids any other package from importing them. `jobs` is the
  exception: the worker's task registration imports it.
- **Components form a one-way graph**, enforced as a `layers` contract:
  `gapplan | resume` → `target` → `assessment` → `rolemap` →
  `identity | profile | market`.
- **The crawl logic belongs to `market`.** The board adapters, board discovery,
  politeness rules and one crawl run live in `advisor/market/crawling/`.
  `crawler/` keeps only its loop. The worker's manual refresh gets a
  crawler-role connection through `Container.open_crawl_ingest()`, so `market`
  imports nothing outside itself.
- **The fan-out read moves into `market`.** `MarketService.owners_affected_by`
  now answers which users watch a changed company or market, in the same
  fan-out transaction. The dispatcher calls it.
- **Four deviations from the guideline:**
  - **`kernel/` stays a top-level package outside the application.** It holds
    database sessions, the outbox, the queue app, token signing, envelope
    crypto, object storage, the AI gateway, guarded fetch and embeddings. Those
    are infrastructure, not business capabilities. The security rules are
    written against these exact packages: who may decrypt, that the crawler
    never reaches the gateway, and that `profile` never reaches the gateway.
    A contract keeps the kernel free of any component or deployable.
  - **`wiring/` is one composition root shared by four deployables**, rather
    than living inside `api/`. The worker, crawler and CLI must not import the
    web framework to get their wiring. The crawler's wiring is its own module
    (`wiring/crawl.py`), so the crawler process never loads the secret-holding
    parts of the container. A contract proves it (`crawler-holds-no-secrets`).
  - **Tests keep `unit/` and `integration/` roots, each mirroring `src/`**,
    rather than one mirrored tree with tiers chosen by marker.
  - **Private submodules carry plain names** (`service.py`, `domain/`,
    `infra/`), not the guideline's `_` prefix. In Python, a package's
    `__init__.py` already defines what the package exposes, so a prefix on
    every file restates it. The import-linter contracts, which name each
    component's submodules, are what enforce the boundary.

## Consequences

**Easier**

- Work on one capability stays in one folder. A component can change its
  entities, queries or storage without touching a caller, and import-linter
  says so the moment someone reaches past an `__init__.py`.
- "No framework in the application" is one contract against `advisor`.
  Routes, task registration and entrypoints can no longer sit inside a
  component.
- The crawler process imports strictly less than before. The old
  `app/crawler_main.py` imported `app.container`, and through it every service.
- Extracting a component into its own service is close to a folder move: its
  `__init__.py` becomes the service contract.

**Harder**

- Layering inside a component (use case → domain → data access) is no longer
  visible as folders. It is kept by the `pure-domain` contract, by convention
  and by review.
- `__init__.py` files must be kept in step with what callers need. A route that
  wants a domain constant (for example `MAX_ROLE_COUNT`) now needs it exported,
  where it used to import `domain.rolemap` directly.
- Tests of a component's private modules sit in that component's test folder
  and import submodule paths. import-linter does not check `tests/`, so
  keeping other tests off those paths is a review matter.
- Nothing in a submodule's name tells a reader it is private. Only the
  import-linter contracts guard the boundary, so a new submodule has to be
  added to its component's contract, and a deep import from `tests/` goes
  unchecked.
- `kernel/` remains the one shared bucket the guideline rules out. A new piece
  of technical code needs a judgement: does it belong in the kernel or in a
  component?
- Every path in older docs moved. ADRs 0001, 0002, 0003, 0005 and 0007 still
  cite `modules/…` and `domain/…` paths, and stay as written because accepted
  records are immutable.
- A component's tests are split between two tier roots, so its unit and
  integration tests are not side by side.

## Alternatives considered

- **Split `kernel/` into application components** (`advisor/ai_gateway/`,
  `advisor/crypto/`, …), with the queue app moving to `worker/` and token
  verification to `api/`. That follows the guideline to the letter, but it
  would put infrastructure next to business capabilities as if it were one.
  It would also re-address every security contract and every mention of them
  in `technical_boundaries.md`. Lost on cost versus benefit: the kernel holds
  no business rules, and a contract already keeps it free of components.
- **Keep the old layout.** Lost for the reasons in the guideline's ADR 0003:
  capabilities stay scattered and their internals stay public.
- **One mirrored `tests/` tree, tiers chosen by the `integration` marker.**
  Closer to the guideline's "tier by what a test needs". Lost because the
  tier roots keep `make test-unit` and `make test-integration` choosing by path,
  unchanged, and a test cannot land in the hermetic run by forgetting a marker.
- **`_`-prefixed private submodules, as the guideline asks.** They would mark
  privacy in every path, but they duplicate what `__init__.py` already says and
  clutter every import inside a component. Lost on readability.
- **Keep the crawl adapters in `crawler/` and inject them into `market`.**
  This avoids moving code, but it leaves parsing and normalising postings, which
  are business rules about market data, in a delivery mechanism.
