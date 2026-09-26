"""In-memory market storage: the domain's repository interfaces, with no database.

Use cases are tested here for what they decide, not for SQL. Every scope sees
the same store, as every transaction sees the same tables. Events land in
``store.events`` only when a scope exits cleanly, as the real unit of work
commits them.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from advisor.market.domain import (
    Company,
    CompanyFilter,
    CompanySubscription,
    CrawlSource,
    CrawlSourceFilter,
    JobPosting,
    JobPostingFilter,
    ManualRefresh,
    ManualRefreshFilter,
    MarketEvent,
    MarketPreference,
    MarketPreferenceFilter,
    PostingEmbedding,
    PostingEmbeddingFilter,
    PostingScope,
    PostingStatus,
    PrivateJobPosting,
    PrivateJobPostingFilter,
    SourceOrigin,
    SubscriptionFilter,
)
from tests.unit.kernel.db.fake_repository import FakeRepository


@dataclass
class Store:
    companies: dict[uuid.UUID, Company] = field(default_factory=dict)
    sources: dict[uuid.UUID, CrawlSource] = field(default_factory=dict)
    postings: dict[uuid.UUID, JobPosting] = field(default_factory=dict)
    embeddings: dict[uuid.UUID, PostingEmbedding] = field(default_factory=dict)
    subscriptions: dict[uuid.UUID, CompanySubscription] = field(default_factory=dict)
    markets: dict[uuid.UUID, MarketPreference] = field(default_factory=dict)
    private_postings: dict[uuid.UUID, PrivateJobPosting] = field(default_factory=dict)
    refreshes: dict[uuid.UUID, ManualRefresh] = field(default_factory=dict)
    events: list[MarketEvent] = field(default_factory=list)


def _set(value: Any, expected: Any) -> bool:
    """A filter field left None matches everything."""
    return expected is None or value == expected


# --- shared zone -----------------------------------------------------------


class FakeCompanies(FakeRepository[Company, CompanyFilter]):
    noun = "company"

    def matches(self, entity: Company, filter: CompanyFilter) -> bool:
        return (filter.ids is None or entity.id in filter.ids) and _set(
            entity.normalized_name, filter.normalized_name
        )


class FakeSources(FakeRepository[CrawlSource, CrawlSourceFilter]):
    noun = "crawl source"

    def matches(self, entity: CrawlSource, filter: CrawlSourceFilter) -> bool:
        return (
            _set(entity.status, filter.status)
            and _set(entity.origin, filter.origin)
            and _set(entity.company_id, filter.company_id)
            and _set(entity.kind, filter.kind)
            and _set(entity.endpoint, filter.endpoint)
        )


class FakePostings(FakeRepository[JobPosting, JobPostingFilter]):
    noun = "job posting"

    def __init__(self, store: Store) -> None:
        super().__init__(store.postings)
        self._store = store

    def matches(self, entity: JobPosting, filter: JobPostingFilter) -> bool:
        embedded = self._store.embeddings.get(entity.id)
        return (
            (filter.ids is None or entity.id in filter.ids)
            and _set(entity.canonical_key, filter.canonical_key)
            and _set(entity.status, filter.status)
            and (filter.has_salary is None or (entity.salary is not None) == filter.has_salary)
            and (
                filter.missing_embedding_for is None
                or embedded is None
                or embedded.model_name != filter.missing_embedding_for
            )
        )

    async def expire_unseen(self, source_id: uuid.UUID, seen_keys: set[str]) -> int:
        expired = 0
        for posting in self._store.postings.values():
            if (
                posting.crawl_source_id == source_id
                and posting.status is PostingStatus.OPEN
                and posting.canonical_key not in seen_keys
            ):
                posting.status = PostingStatus.EXPIRED
                expired += 1
        return expired

    async def get_open_in_scope(self, scope: PostingScope) -> list[JobPosting]:
        baseline = {s.id for s in self._store.sources.values() if s.origin is SourceOrigin.BASELINE}
        opened = await self.get_list(JobPostingFilter(status=PostingStatus.OPEN))
        return [
            p
            for p in opened
            if p.company_id in scope.company_ids
            or p.location in scope.markets
            or (scope.includes_baseline and p.crawl_source_id in baseline)
        ]


class FakeEmbeddings(FakeRepository[PostingEmbedding, PostingEmbeddingFilter]):
    id_field = "posting_id"
    created_field = "computed_at"
    updated_field = None
    noun = "posting embedding"

    def matches(self, entity: PostingEmbedding, filter: PostingEmbeddingFilter) -> bool:
        return (filter.posting_ids is None or entity.posting_id in filter.posting_ids) and _set(
            entity.model_name, filter.model_name
        )


# --- owner zone ------------------------------------------------------------


class FakeSubscriptions(FakeRepository[CompanySubscription, SubscriptionFilter]):
    owner_field = "owner_id"
    noun = "subscription"

    def matches(self, entity: CompanySubscription, filter: SubscriptionFilter) -> bool:
        return _set(entity.company_id, filter.company_id) and _set(
            entity.role_title, filter.role_title
        )


class FakeMarkets(FakeRepository[MarketPreference, MarketPreferenceFilter]):
    owner_field = "owner_id"
    noun = "market preference"

    def matches(self, entity: MarketPreference, filter: MarketPreferenceFilter) -> bool:
        return _set(entity.market, filter.market)


class FakePrivatePostings(FakeRepository[PrivateJobPosting, PrivateJobPostingFilter]):
    owner_field = "owner_id"
    noun = "job description"

    def matches(self, entity: PrivateJobPosting, filter: PrivateJobPostingFilter) -> bool:
        return filter.has_vector is None or (entity.vector is not None) == filter.has_vector


class FakeRefreshes(FakeRepository[ManualRefresh, ManualRefreshFilter]):
    created_field = "requested_at"
    updated_field = None
    owner_field = "owner_id"
    noun = "manual refresh"

    def matches(self, entity: ManualRefresh, filter: ManualRefreshFilter) -> bool:
        return (
            filter.requested_since is None
            or entity.requested_at is None
            or entity.requested_at >= filter.requested_since
        )


# --- scopes ----------------------------------------------------------------


class _Scope:
    def __init__(self) -> None:
        self.pending: list[MarketEvent] = []

    def record(self, event: MarketEvent) -> None:
        self.pending.append(event)


class FakeShared(_Scope):
    def __init__(self, store: Store) -> None:
        super().__init__()
        self.companies = FakeCompanies(store.companies)
        self.sources = FakeSources(store.sources)
        self.postings = FakePostings(store)
        self.embeddings = FakeEmbeddings(store.embeddings)


class FakeOwner(_Scope):
    def __init__(self, store: Store, owner_id: uuid.UUID) -> None:
        super().__init__()
        self.subscriptions = FakeSubscriptions(store.subscriptions, owner_id=owner_id)
        self.markets = FakeMarkets(store.markets, owner_id=owner_id)
        self.private_postings = FakePrivatePostings(store.private_postings, owner_id=owner_id)
        self.refreshes = FakeRefreshes(store.refreshes, owner_id=owner_id)


class FakeFanout:
    def __init__(self, store: Store) -> None:
        self.subscriptions = FakeSubscriptions(store.subscriptions)
        self.markets = FakeMarkets(store.markets)


class FakeMarketUnitOfWork:
    def __init__(self, store: Store | None = None) -> None:
        self.store = store or Store()

    @asynccontextmanager
    async def for_owner(self, owner_id: uuid.UUID) -> AsyncIterator[FakeOwner]:
        scope = FakeOwner(self.store, owner_id)
        yield scope
        self.store.events.extend(scope.pending)

    @asynccontextmanager
    async def shared(self) -> AsyncIterator[FakeShared]:
        scope = FakeShared(self.store)
        yield scope
        self.store.events.extend(scope.pending)

    @asynccontextmanager
    async def fanout(self) -> AsyncIterator[FakeFanout]:
        yield FakeFanout(self.store)
