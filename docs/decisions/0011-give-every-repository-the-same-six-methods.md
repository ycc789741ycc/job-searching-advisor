# 0011. Give every repository the same six methods

**Status:** Accepted — 2026-09-27. Supersedes [0010](0010-define-repositories-in-the-domain-in-domain-types.md).

## Context

ADR 0010 moved `market`'s use cases onto repository interfaces defined in the
domain, in domain types. It shaped each method around the query a use case
needed: `find`, `at_company`, `by_endpoint`, `exists_for_company`, `vectors`,
`count_since` and so on. Every repository came out a different shape, ordering
and paging were decided per method, and a new question meant a new method on
the interface, the SQL class and the fake.

The design guideline has since settled the repository contract (its ADRs 0005
and 0006, and `base/backend/data-access.md`):
- every repository has the same six methods and a per-aggregate filter;
- lists are newest first and paginated;
- implementations are named after their technology;
- a component's factory builds them from infrastructure handles;
- a lint rule keeps the ORM inside persistence code.

## Decision

Everything in ADR 0010 that the guideline also requires stays:
- The interfaces live in the component's `domain/` and speak only in entities
  and value objects.
- Use cases depend on them alone.
- `infra/` implements them and maps rows to entities and back.
- The unit of work has one scope per data zone (`for_owner`, `shared`,
  `fanout`). The guideline leaves transactions to the codebase.
- Events are recorded on the scope and written to the outbox in the same
  transaction.

On top of that:

- **Every repository has exactly six methods**: `create`, `get`, `get_list`,
  `get_count`, `update`, `delete`. They are declared once, as the generic
  `Repository[Entity, Filter]` Protocol in `advisor/market/domain/repositories.py`.
  - `create` returns the stored entity with its timestamps.
  - `get` returns `None` when nothing matches.
  - `update` and `delete` raise `NotFoundError` when the entity is missing.
- **One frozen filter per aggregate** (`SubscriptionFilter`, `JobPostingFilter`,
  …). Fields default to `None`, meaning "don't filter", and set fields combine
  with AND. A new question is a new field.
- **`get_list` is newest first and paged.** It sorts by `created_at` descending,
  ties broken by id descending, with `page=1, page_size=None` by default.
  - `kernel.paging.check_page` rejects an invalid page as a `ValidationError`.
  - `page_size=None` is used only where the filter keeps the set small: one
    user's subscriptions, the baseline list, the ids of one role.
  - The fan-out over every user's subscriptions pages through them 500 at a
    time.
- **Extra methods only where the six cannot express the operation.** There are
  two, both on `JobPostingRepository`:
  - `expire_unseen`, a bulk update;
  - `get_open_in_scope`, an OR across watched companies, chosen markets and
    baseline sources.
- **Three aggregates are now explicit**, because the six methods needed an
  entity to return: `MarketPreference`, `ManualRefresh` and `PostingEmbedding`.
  An aggregate whose table has no `created_at` sorts on its creation column:
  `requested_at` for `ManualRefresh`, `computed_at` for `PostingEmbedding`.
- **The six methods are written once** in `kernel.db.repository.SqlAlchemyRepository`.
  A component's `SqlAlchemy<Aggregate>Repository` supplies the model, the
  mappers and one condition per filter field. An owner-bound repository adds
  `owner_id = :owner` to every read and write, on top of RLS.
  - The unit tests' in-memory twin is `tests/unit/kernel/db/fake_repository.py`.
    It keeps the same contract and stores copies.
- **The declarative base sets `eager_defaults`.** Server-set timestamps come
  back through `RETURNING` on the same statement, so `create` and `update`
  can return them without a lazy reload, which fails under asyncio.
- **The component builds itself.** `advisor.market` exports
  `create_market_service(database, …)` and `create_crawl_ingest(database)`.
  The composition root, the seed CLI and the integration tests call them.
  Nothing else constructs a repository or a unit of work, and
  `SqlAlchemyMarketUnitOfWork` stays private.
- **Rule `orm-only-in-persistence`** replaces `use-cases-know-no-persistence`.
  It forbids `sqlalchemy`, `pgvector`, `asyncpg`, `kernel.db` and the outbox
  writer in the component's `domain`, `service`, `jobs`, `crawling` and
  `baseline`, directly or indirectly. Only `infra/` and the factory may import
  them.

## Consequences

**Easier**

- There is one repository shape to read, review and fake. A new aggregate is a
  filter, two mappers and a small subclass.
- Every list is ordered and paged the same way, which maps straight onto list
  endpoints when they grow paging.
- Only a caller that needs a total pays for a COUNT.
- The filter types list every question a use case asks of an aggregate.

**Harder**

- Joins are gone from the interface. Company names for postings and sources
  now come from a second, batched query (`CompanyFilter(ids=…)`), and "does it
  exist" is a `get_count` or a `get_list(page_size=1)`.
- `set_coverage`, which was one bulk UPDATE, is now a load and an update per
  subscription at that company. A user has a handful of roles per company.
- Lists that were in whatever order Postgres returned are now newest first:
  subscriptions, pasted JDs and postings in scope. The API returns these lists,
  so the SPA sees the new order.
- The fan-out scope loads whole subscription and preference rows, not just
  owner ids. The fan-out policy has always allowed that. The migration's
  comment about "two columns" describes what the dispatcher needs, not what the
  policy limits.
- Every aggregate needs a `created_at` on its entity, filled by `create`.
- Creating several rows in one transaction gives them the same `created_at`
  (Postgres `now()` is the transaction start), so their order falls to the id
  tiebreak.

## Alternatives considered

- **Keep ADR 0010's query-shaped methods.** They read naturally, but every
  repository differs and ordering and paging are reinvented per method. Lost
  to the guideline.
- **Hand-write the six methods per aggregate.** No shared base, so each class
  reads on its own. Lost because eight copies of paging, ordering and
  owner-binding would drift, and the fakes would need eight copies too.
- **Keep bulk `set_coverage` as an extra method.** Lost because the set it
  touches is tiny, and the guideline admits an extra method only for what the
  six cannot express, not for saving a few statements.
