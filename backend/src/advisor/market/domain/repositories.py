"""How the market's use cases reach stored data: interfaces in domain terms.

Every method speaks in the entities and value objects of this package, never in
rows. ``advisor.market.infra`` implements them; use cases depend only on these.

The unit of work hands out repositories per *zone*, mirroring where the data
lives (docs/technical_boundaries.md section 3):

* ``for_owner`` — one user's owner-zone data, and nothing else of anyone's.
* ``shared`` — the shared zone: companies, sources, crawled postings.
* ``fanout`` — the one cross-user read: who watches a company or a market.

Each scope is one transaction. Events recorded in it are committed with it.
"""

from __future__ import annotations

import uuid
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol

from advisor.market.domain.entities import (
    Company,
    CompanySubscription,
    CrawlSource,
    DueSource,
    JobPosting,
    PostingScope,
    PrivateJobPosting,
)
from advisor.market.domain.events import MarketEvent
from advisor.market.domain.posting import Coverage, SalaryRange

# --- shared zone -----------------------------------------------------------


class CompanyRepository(Protocol):
    async def get(self, company_id: uuid.UUID) -> Company | None: ...

    async def by_normalized_name(self, normalized_name: str) -> Company | None: ...

    async def add(self, company: Company) -> None: ...


class CrawlSourceRepository(Protocol):
    async def get(self, source_id: uuid.UUID) -> CrawlSource | None: ...

    async def due(self) -> list[DueSource]:
        """Every active source, with its company's name where it has one."""
        ...

    async def by_endpoint(self, endpoint: str) -> CrawlSource | None: ...

    async def by_kind_and_endpoint(self, kind: str, endpoint: str) -> CrawlSource | None: ...

    async def exists_for_company(self, company_id: uuid.UUID) -> bool: ...

    async def baseline(self) -> list[CrawlSource]: ...

    async def add(self, source: CrawlSource) -> None: ...

    async def save(self, source: CrawlSource) -> None: ...


class JobPostingRepository(Protocol):
    async def by_canonical_key(self, key: str) -> JobPosting | None: ...

    async def add(self, posting: JobPosting) -> None: ...

    async def save(self, posting: JobPosting) -> None: ...

    async def expire_unseen(self, source_id: uuid.UUID, seen_keys: set[str]) -> int:
        """Mark this source's open postings that were not seen as expired, never
        deleted. Returns how many."""
        ...

    async def open_in_scope(self, scope: PostingScope) -> list[tuple[JobPosting, str]]:
        """Open postings in the scope, each with its company's name."""
        ...

    async def salary_ranges(self, posting_ids: list[uuid.UUID]) -> list[SalaryRange]:
        """The published pay of those postings; postings without pay are absent."""
        ...

    async def needing_embeddings(self, model_name: str, limit: int) -> list[JobPosting]: ...

    async def embeddings(
        self, posting_ids: list[uuid.UUID], model_name: str
    ) -> dict[uuid.UUID, list[float]]: ...

    async def add_embeddings(
        self, model_name: str, vectors: dict[uuid.UUID, list[float]]
    ) -> None: ...


class SharedMarket(Protocol):
    @property
    def companies(self) -> CompanyRepository: ...

    @property
    def sources(self) -> CrawlSourceRepository: ...

    @property
    def postings(self) -> JobPostingRepository: ...

    def record(self, event: MarketEvent) -> None: ...


# --- fan-out ---------------------------------------------------------------


class Watchers(Protocol):
    """Who watches what, across users. Readable only in the fan-out scope."""

    async def of_company(self, company_id: uuid.UUID) -> set[uuid.UUID]: ...

    async def of_market(self, market: str) -> set[uuid.UUID]: ...

    async def watched_boards(self) -> list[tuple[uuid.UUID, str, str | None]]:
        """Every distinct (company id, company name, link) anyone subscribed with,
        with no owner attached."""
        ...


# --- owner zone ------------------------------------------------------------


class SubscriptionRepository(Protocol):
    async def all(self) -> list[CompanySubscription]: ...

    async def get(self, subscription_id: uuid.UUID) -> CompanySubscription | None: ...

    async def find(self, company_id: uuid.UUID, role_title: str) -> CompanySubscription | None: ...

    async def at_company(self, company_id: uuid.UUID) -> list[CompanySubscription]: ...

    async def add(self, subscription: CompanySubscription) -> None: ...

    async def save(self, subscription: CompanySubscription) -> None: ...

    async def remove(self, subscription_id: uuid.UUID) -> None: ...

    async def set_coverage(self, company_id: uuid.UUID, coverage: Coverage) -> None:
        """Coverage belongs to the company's board, so it is set for every role
        watched there at once."""
        ...


class MarketPreferenceRepository(Protocol):
    async def all(self) -> list[str]: ...

    async def has(self, market: str) -> bool: ...

    async def add(self, market: str) -> None: ...

    async def remove(self, market: str) -> None: ...


class PrivatePostingRepository(Protocol):
    async def all(self) -> list[PrivateJobPosting]: ...

    async def get(self, posting_id: uuid.UUID) -> PrivateJobPosting | None: ...

    async def add(self, posting: PrivateJobPosting) -> None: ...

    async def vectors(self) -> dict[uuid.UUID, list[float]]:
        """Embeddings of the pasted JDs that have one."""
        ...

    async def set_vector(self, posting_id: uuid.UUID, vector: list[float]) -> None: ...


class ManualRefreshRepository(Protocol):
    async def count_since(self, since: datetime) -> int: ...

    async def record(self, company_id: uuid.UUID) -> None: ...


class OwnerMarket(Protocol):
    @property
    def subscriptions(self) -> SubscriptionRepository: ...

    @property
    def markets(self) -> MarketPreferenceRepository: ...

    @property
    def private_postings(self) -> PrivatePostingRepository: ...

    @property
    def refreshes(self) -> ManualRefreshRepository: ...

    def record(self, event: MarketEvent) -> None: ...


# --- unit of work ----------------------------------------------------------


class MarketUnitOfWork(Protocol):
    def for_owner(self, owner_id: uuid.UUID) -> AbstractAsyncContextManager[OwnerMarket]: ...

    def shared(self) -> AbstractAsyncContextManager[SharedMarket]: ...

    def fanout(self) -> AbstractAsyncContextManager[Watchers]: ...
