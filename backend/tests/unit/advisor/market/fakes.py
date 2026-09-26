"""In-memory market storage: the domain's repository interfaces, with no database.

It exists so use cases can be tested for what they decide, not for SQL. Each
scope sees the same store; events land in ``store.events`` only when the scope
exits cleanly, as the real unit of work commits them.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

from advisor.market.domain import (
    Company,
    CompanySubscription,
    Coverage,
    CrawlSource,
    DueSource,
    JobPosting,
    MarketEvent,
    PostingScope,
    PostingStatus,
    PrivateJobPosting,
    SalaryRange,
    SourceOrigin,
    SourceStatus,
)


@dataclass
class Store:
    companies: dict[uuid.UUID, Company] = field(default_factory=dict)
    sources: dict[uuid.UUID, CrawlSource] = field(default_factory=dict)
    postings: dict[uuid.UUID, JobPosting] = field(default_factory=dict)
    embeddings: dict[tuple[uuid.UUID, str], list[float]] = field(default_factory=dict)
    subscriptions: dict[uuid.UUID, CompanySubscription] = field(default_factory=dict)
    markets: dict[uuid.UUID, set[str]] = field(default_factory=dict)
    private_postings: dict[uuid.UUID, PrivateJobPosting] = field(default_factory=dict)
    refreshes: list[tuple[uuid.UUID, uuid.UUID, datetime]] = field(default_factory=list)
    events: list[MarketEvent] = field(default_factory=list)


# Stored copies, so a use case that forgets to save is caught.
def _copy[T](value: T) -> T:
    return copy.deepcopy(value)


class FakeCompanies:
    def __init__(self, store: Store) -> None:
        self._s = store

    async def get(self, company_id: uuid.UUID) -> Company | None:
        return _copy(self._s.companies.get(company_id))

    async def by_normalized_name(self, normalized_name: str) -> Company | None:
        for company in self._s.companies.values():
            if company.normalized_name == normalized_name:
                return _copy(company)
        return None

    async def add(self, company: Company) -> None:
        self._s.companies[company.id] = _copy(company)


class FakeSources:
    def __init__(self, store: Store) -> None:
        self._s = store

    async def get(self, source_id: uuid.UUID) -> CrawlSource | None:
        return _copy(self._s.sources.get(source_id))

    async def due(self) -> list[DueSource]:
        return [
            DueSource(
                source=_copy(source),
                company_name=self._s.companies[source.company_id].name
                if source.company_id in self._s.companies
                else None,
            )
            for source in self._s.sources.values()
            if source.status is SourceStatus.ACTIVE
        ]

    async def by_endpoint(self, endpoint: str) -> CrawlSource | None:
        return next((_copy(s) for s in self._s.sources.values() if s.endpoint == endpoint), None)

    async def by_kind_and_endpoint(self, kind: str, endpoint: str) -> CrawlSource | None:
        return next(
            (
                _copy(s)
                for s in self._s.sources.values()
                if s.kind == kind and s.endpoint == endpoint
            ),
            None,
        )

    async def exists_for_company(self, company_id: uuid.UUID) -> bool:
        return any(s.company_id == company_id for s in self._s.sources.values())

    async def baseline(self) -> list[CrawlSource]:
        return [_copy(s) for s in self._s.sources.values() if s.origin is SourceOrigin.BASELINE]

    async def add(self, source: CrawlSource) -> None:
        self._s.sources[source.id] = _copy(source)

    async def save(self, source: CrawlSource) -> None:
        assert source.id in self._s.sources, "saved a source that was never added"
        self._s.sources[source.id] = _copy(source)


class FakePostings:
    def __init__(self, store: Store) -> None:
        self._s = store

    async def by_canonical_key(self, key: str) -> JobPosting | None:
        return next((_copy(p) for p in self._s.postings.values() if p.canonical_key == key), None)

    async def add(self, posting: JobPosting) -> None:
        self._s.postings[posting.id] = _copy(posting)

    async def save(self, posting: JobPosting) -> None:
        assert posting.id in self._s.postings, "saved a posting that was never added"
        self._s.postings[posting.id] = _copy(posting)

    async def expire_unseen(self, source_id: uuid.UUID, seen_keys: set[str]) -> int:
        expired = 0
        for posting in self._s.postings.values():
            if (
                posting.crawl_source_id == source_id
                and posting.status is PostingStatus.OPEN
                and posting.canonical_key not in seen_keys
            ):
                posting.status = PostingStatus.EXPIRED
                expired += 1
        return expired

    async def open_in_scope(self, scope: PostingScope) -> list[tuple[JobPosting, str]]:
        baseline_sources = {
            s.id for s in self._s.sources.values() if s.origin is SourceOrigin.BASELINE
        }
        return [
            (_copy(p), self._s.companies[p.company_id].name)
            for p in self._s.postings.values()
            if p.status is PostingStatus.OPEN
            and (
                p.company_id in scope.company_ids
                or p.location in scope.markets
                or (scope.includes_baseline and p.crawl_source_id in baseline_sources)
            )
        ]

    async def salary_ranges(self, posting_ids: list[uuid.UUID]) -> list[SalaryRange]:
        return [
            p.salary
            for i in posting_ids
            if (p := self._s.postings.get(i)) is not None and p.salary is not None
        ]

    async def needing_embeddings(self, model_name: str, limit: int) -> list[JobPosting]:
        missing = [
            p for p in self._s.postings.values() if (p.id, model_name) not in self._s.embeddings
        ]
        return [_copy(p) for p in missing[:limit]]

    async def embeddings(
        self, posting_ids: list[uuid.UUID], model_name: str
    ) -> dict[uuid.UUID, list[float]]:
        return {
            i: self._s.embeddings[(i, model_name)]
            for i in posting_ids
            if (i, model_name) in self._s.embeddings
        }

    async def add_embeddings(self, model_name: str, vectors: dict[uuid.UUID, list[float]]) -> None:
        for posting_id, vector in vectors.items():
            self._s.embeddings[(posting_id, model_name)] = vector


class FakeWatchers:
    def __init__(self, store: Store) -> None:
        self._s = store

    async def of_company(self, company_id: uuid.UUID) -> set[uuid.UUID]:
        return {s.owner_id for s in self._s.subscriptions.values() if s.company_id == company_id}

    async def of_market(self, market: str) -> set[uuid.UUID]:
        return {owner for owner, markets in self._s.markets.items() if market in markets}

    async def watched_boards(self) -> list[tuple[uuid.UUID, str, str | None]]:
        return list(
            dict.fromkeys(
                (s.company_id, s.company_name, s.url) for s in self._s.subscriptions.values()
            )
        )


class FakeSubscriptions:
    def __init__(self, store: Store, owner_id: uuid.UUID) -> None:
        self._s, self._owner = store, owner_id

    def _mine(self) -> list[CompanySubscription]:
        return [s for s in self._s.subscriptions.values() if s.owner_id == self._owner]

    async def all(self) -> list[CompanySubscription]:
        return [_copy(s) for s in self._mine()]

    async def get(self, subscription_id: uuid.UUID) -> CompanySubscription | None:
        return next((_copy(s) for s in self._mine() if s.id == subscription_id), None)

    async def find(self, company_id: uuid.UUID, role_title: str) -> CompanySubscription | None:
        return next(
            (
                _copy(s)
                for s in self._mine()
                if s.company_id == company_id and s.role_title == role_title
            ),
            None,
        )

    async def at_company(self, company_id: uuid.UUID) -> list[CompanySubscription]:
        return [_copy(s) for s in self._mine() if s.company_id == company_id]

    async def add(self, subscription: CompanySubscription) -> None:
        self._s.subscriptions[subscription.id] = _copy(subscription)

    async def save(self, subscription: CompanySubscription) -> None:
        assert subscription.id in self._s.subscriptions
        self._s.subscriptions[subscription.id] = _copy(subscription)

    async def remove(self, subscription_id: uuid.UUID) -> None:
        if any(s.id == subscription_id for s in self._mine()):
            del self._s.subscriptions[subscription_id]

    async def set_coverage(self, company_id: uuid.UUID, coverage: Coverage) -> None:
        for s in self._mine():
            if s.company_id == company_id:
                s.coverage = coverage


class FakeMarkets:
    def __init__(self, store: Store, owner_id: uuid.UUID) -> None:
        self._markets = store.markets.setdefault(owner_id, set())

    async def all(self) -> list[str]:
        return sorted(self._markets)

    async def has(self, market: str) -> bool:
        return market in self._markets

    async def add(self, market: str) -> None:
        self._markets.add(market)

    async def remove(self, market: str) -> None:
        self._markets.discard(market)


class FakePrivatePostings:
    def __init__(self, store: Store, owner_id: uuid.UUID) -> None:
        self._s, self._owner = store, owner_id

    def _mine(self) -> list[PrivateJobPosting]:
        return [p for p in self._s.private_postings.values() if p.owner_id == self._owner]

    async def all(self) -> list[PrivateJobPosting]:
        return [_copy(p) for p in self._mine()]

    async def get(self, posting_id: uuid.UUID) -> PrivateJobPosting | None:
        return next((_copy(p) for p in self._mine() if p.id == posting_id), None)

    async def add(self, posting: PrivateJobPosting) -> None:
        self._s.private_postings[posting.id] = _copy(posting)

    async def vectors(self) -> dict[uuid.UUID, list[float]]:
        return {p.id: p.vector for p in self._mine() if p.vector is not None}

    async def set_vector(self, posting_id: uuid.UUID, vector: list[float]) -> None:
        for p in self._mine():
            if p.id == posting_id:
                p.vector = vector


class FakeRefreshes:
    def __init__(self, store: Store, owner_id: uuid.UUID) -> None:
        self._s, self._owner = store, owner_id

    async def count_since(self, since: datetime) -> int:
        return sum(1 for owner, _, at in self._s.refreshes if owner == self._owner and at >= since)

    async def record(self, company_id: uuid.UUID) -> None:
        self._s.refreshes.append((self._owner, company_id, datetime.now(UTC)))


class _Scope:
    def __init__(self) -> None:
        self.pending: list[MarketEvent] = []

    def record(self, event: MarketEvent) -> None:
        self.pending.append(event)


class FakeShared(_Scope):
    def __init__(self, store: Store) -> None:
        super().__init__()
        self.companies = FakeCompanies(store)
        self.sources = FakeSources(store)
        self.postings = FakePostings(store)


class FakeOwner(_Scope):
    def __init__(self, store: Store, owner_id: uuid.UUID) -> None:
        super().__init__()
        self.subscriptions = FakeSubscriptions(store, owner_id)
        self.markets = FakeMarkets(store, owner_id)
        self.private_postings = FakePrivatePostings(store, owner_id)
        self.refreshes = FakeRefreshes(store, owner_id)


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
    async def fanout(self) -> AsyncIterator[FakeWatchers]:
        yield FakeWatchers(self.store)
