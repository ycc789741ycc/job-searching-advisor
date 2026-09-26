# 0010. Define repositories in the domain, in domain types

**Status:** Superseded by [0011](0011-give-every-repository-the-same-six-methods.md) — 2026-09-27.

## Context

After the backend moved to components (ADR 0009), each component's use cases
still reached the database themselves. `service.py` and `jobs.py` opened
SQLAlchemy sessions, ran `select(...)`, mutated ORM rows and wrote outbox
events through the session. Seven of eight components had no repository layer.
`identity` had one, but its repositories returned ORM models.

So a schema change, an ORM change or a rewritten query landed in business code.
Use cases could not be tested without a database. This also broke the design
guideline's data-access rule: all DB access goes through a repository layer,
never raw queries in business logic.

## Decision

A component's repository interfaces live in its domain and speak only in
domain types. `infra/` implements them.

```
advisor/<c>/
  domain/entities.py       entities: plain dataclasses with their own rules
  domain/events.py         domain events as dataclasses
  domain/repositories.py   Protocols: repositories and the unit of work
  service.py, jobs.py      use cases, depending on domain/repositories.py only
  infra/mappers.py         ORM row <-> entity
  infra/repositories.py    SQL implementations of the Protocols
  infra/unit_of_work.py    session scopes, and domain event -> outbox row
```

- **The unit of work is a domain Protocol with one scope per data zone.** The
  zones are `for_owner(owner_id)`, `shared()` and `fanout()`. Each scope is one
  transaction and maps onto `Database.for_user`, `shared` or `fanout`, so
  row-level security and the fan-out policy are enforced exactly as before.
- **Use cases record domain events on the scope** (`scope.record(event)`). The
  SQL unit of work writes them to the outbox in the same transaction, just
  before it commits, under the same names and payloads as before.
- **Repository methods are shaped by the queries use cases need**
  (`open_in_scope(scope)`, `expire_unseen(source_id, keys)`), not a generic
  CRUD surface. That keeps each query a single statement, as it was.
- **Entities are saved explicitly** (`save(entity)`). ORM change tracking stays
  inside `infra/`.
- **Each component's `__init__.py` exports its SQL unit of work**, because a
  component owns its data access. The composition root and integration tests
  construct services with it.
- **import-linter rule `use-cases-know-no-persistence` enforces it.** A
  migrated component's `service` and `jobs` may not import `sqlalchemy`,
  `pgvector`, `kernel.db`, the outbox writer or their own `infra`, directly or
  indirectly. The existing `pure-domain` rule keeps `domain/repositories.py`
  itself free of the ORM.
- **The clock moves to `kernel.clock`**, so taking the time does not import
  the database package.
- **Components move one at a time**, `market` first. Each joins the rule as it
  lands.

## Consequences

**Easier**

- A schema, ORM or query change stays in `infra/`. Use cases don't change.
- Use cases are unit-tested against in-memory fakes of the Protocols, in the
  hermetic tier. That is new for most components.
- Business rules that were buried in query code are visible on entities, for
  example which fields a repeat crawl may overwrite, or that coverage belongs
  to a company's board.
- Outbox payloads are built in one place per component instead of at each call
  site.

**Harder**

- More code per component: entities, mappers, Protocols, SQL repositories and
  test fakes, where a use case used to hold one query.
- Explicit `save` replaces ORM change tracking. A use case that changes an
  entity and forgets to save it loses the change. The fakes store copies, so
  unit tests catch that.
- Mappers are lossy wherever the schema is looser than the entity. For
  example, a posting row with a minimum salary but no maximum reads back with
  max = min.
- Until every component has moved, the codebase has two styles, and the rule
  lists components by name.
- Integration tests and the composition root build services with the
  component's SQL unit of work, not a bare `Database`.

## Alternatives considered

- **Repositories that return ORM models, as `identity` had.** Less code, and
  change tracking keeps working. Lost because the interface would be defined
  in persistence terms: a schema change would still reach use cases through
  model attributes, and use cases would still need a database to test.
- **Generic repositories (`get` / `add` / `list(filter)`).** One shape for
  every entity. Lost because the queries that matter (scope filters, bulk
  expiry, vector reads) do not fit a generic filter without leaking query
  language into the domain, or turning single statements into N+1 loops.
- **A unit of work in `kernel` holding every component's repositories.** One
  transaction type for the whole app. Lost because the kernel would then know
  every component (ADR 0009 forbids it), and a cross-component transaction
  would couple components that today only talk through public APIs.
- **Keep sessions in use cases and forbid only raw SQL.** Least churn, but it
  decouples nothing: the session and the ORM models are the persistence layer.
