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

The design guideline at `/Users/yoshi/repo/design-guideline` applies here too.

## Running it

```
cp .env.example .env      # fill in every blank; nothing has a default that matters
make build-infra && make build-app
make start-infra          # Postgres + MinIO, then the least-privilege DB roles
make start-app            # runs migrations to completion first, then api/worker/crawler
```

`make test-unit` is hermetic — it passes on a clean checkout with nothing
running. `make test-integration` assumes infra is up and migrated, and tells you
to run `make start-infra` if it is not. Narrow either with `PATTERN=`.

Supporting targets, never dependencies of the above: `migrate`, `lint`, `scan`,
`gen-client`, and `reset-data` (the only destructive one).

## Shape of the code

```
backend/
  app/        composition root: FastAPI app, worker and crawler entrypoints, queue wiring
  kernel/     technical kernel, no domain: db, outbox, jobs, auth, crypto, storage,
              ai_gateway, fetch, embeddings
  modules/    identity · profile · market · rolemap · assessment
                public.py   the ONLY importable surface
                api.py      FastAPI routers
                domain/     pure rules, no I/O, no framework
                infra/      repositories and adapters
                jobs.py     worker handlers
  crawler/    its own deployable: hostile HTML, no secrets, no user data
web/          React + Vite SPA
```

Six `import-linter` contracts in `.importlinter` enforce those boundaries, and
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

Out, and why: `growth` (goals and gap plans) and `resume` (generation, versions,
chat, export) are Phase 2/3. The hiring bar is `estimated` only — `InterviewReport`
arrives with the reporting flow later. Google login is Phase 2.
