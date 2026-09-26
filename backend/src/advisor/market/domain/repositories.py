"""How the market's use cases reach stored data: interfaces in domain terms.

Every repository has the same six methods (ADR 0011, after the design
guideline's data-access rule):

* ``create`` returns the stored entity, with its timestamps.
* ``get`` returns ``None`` when nothing matches.
* ``get_list`` takes the aggregate's filter and returns one page, newest first.
  ``page`` is 1-based; ``page_size=None`` returns every match.
* ``get_count`` takes the same filter and counts every match.
* ``update`` and ``delete`` raise a not-found error when the entity is missing.

A filter field left ``None`` does not filter; set fields combine with AND. A
new question is a new filter field, not a new method. The two extra methods on
``JobPostingRepository`` are the operations six methods cannot express: a bulk
expiry and an OR query.

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
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from advisor.market.domain.entities import (
    Company,
    CompanySubscription,
    CrawlSource,
    JobPosting,
    ManualRefresh,
    MarketPreference,
    PostingEmbedding,
    PostingScope,
    PrivateJobPosting,
    SourceStatus,
)
from advisor.market.domain.events import MarketEvent
from advisor.market.domain.posting import PostingStatus, SourceOrigin


class Repository[Entity, Filter](Protocol):
    """The six methods, as every market repository has them."""

    async def create(self, entity: Entity) -> Entity: ...

    async def get(self, entity_id: uuid.UUID) -> Entity | None: ...

    async def get_list(
        self, filter: Filter, page: int = 1, page_size: int | None = None
    ) -> list[Entity]: ...

    async def get_count(self, filter: Filter) -> int: ...

    async def update(self, entity: Entity) -> Entity: ...

    async def delete(self, entity_id: uuid.UUID) -> None: ...


# --- shared zone -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CompanyFilter:
    ids: tuple[uuid.UUID, ...] | None = None
    normalized_name: str | None = None


class CompanyRepository(Repository[Company, CompanyFilter], Protocol): ...


@dataclass(frozen=True, slots=True)
class CrawlSourceFilter:
    status: SourceStatus | None = None
    origin: SourceOrigin | None = None
    company_id: uuid.UUID | None = None
    kind: str | None = None
    endpoint: str | None = None


class CrawlSourceRepository(Repository[CrawlSource, CrawlSourceFilter], Protocol): ...


@dataclass(frozen=True, slots=True)
class JobPostingFilter:
    ids: tuple[uuid.UUID, ...] | None = None
    canonical_key: str | None = None
    status: PostingStatus | None = None
    # True: only postings that published pay.
    has_salary: bool | None = None
    # Postings with no embedding yet from this model.
    missing_embedding_for: str | None = None


class JobPostingRepository(Repository[JobPosting, JobPostingFilter], Protocol):
    async def expire_unseen(self, source_id: uuid.UUID, seen_keys: set[str]) -> int:
        """Mark this source's open postings that were not seen as expired, never
        deleted. Returns how many.

        Extra method: a bulk update over every posting of one source, which the
        six methods would turn into one load and one write per posting.
        """
        ...

    async def get_open_in_scope(self, scope: PostingScope) -> list[JobPosting]:
        """Open postings in a user's scope, newest first.

        Extra method: the scope is an OR (a watched company, or a chosen market,
        or a baseline source), which a filter's AND cannot express.
        """
        ...


@dataclass(frozen=True, slots=True)
class PostingEmbeddingFilter:
    posting_ids: tuple[uuid.UUID, ...] | None = None
    model_name: str | None = None


class PostingEmbeddingRepository(Repository[PostingEmbedding, PostingEmbeddingFilter], Protocol):
    """Keyed by posting id: a posting has at most one embedding."""


class SharedMarket(Protocol):
    @property
    def companies(self) -> CompanyRepository: ...

    @property
    def sources(self) -> CrawlSourceRepository: ...

    @property
    def postings(self) -> JobPostingRepository: ...

    @property
    def embeddings(self) -> PostingEmbeddingRepository: ...

    def record(self, event: MarketEvent) -> None: ...


# --- owner zone ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SubscriptionFilter:
    company_id: uuid.UUID | None = None
    role_title: str | None = None


class SubscriptionRepository(Repository[CompanySubscription, SubscriptionFilter], Protocol): ...


@dataclass(frozen=True, slots=True)
class MarketPreferenceFilter:
    market: str | None = None


class MarketPreferenceRepository(
    Repository[MarketPreference, MarketPreferenceFilter], Protocol
): ...


@dataclass(frozen=True, slots=True)
class PrivateJobPostingFilter:
    # True: only pasted JDs that have been embedded.
    has_vector: bool | None = None


class PrivateJobPostingRepository(
    Repository[PrivateJobPosting, PrivateJobPostingFilter], Protocol
): ...


@dataclass(frozen=True, slots=True)
class ManualRefreshFilter:
    requested_since: datetime | None = None


class ManualRefreshRepository(Repository[ManualRefresh, ManualRefreshFilter], Protocol): ...


class OwnerMarket(Protocol):
    @property
    def subscriptions(self) -> SubscriptionRepository: ...

    @property
    def markets(self) -> MarketPreferenceRepository: ...

    @property
    def private_postings(self) -> PrivateJobPostingRepository: ...

    @property
    def refreshes(self) -> ManualRefreshRepository: ...

    def record(self, event: MarketEvent) -> None: ...


# --- fan-out ---------------------------------------------------------------


class FanoutMarket(Protocol):
    """Subscriptions and market choices across every user, read-only.

    The database's fan-out policy allows SELECT here and nothing else, so a
    write through these repositories fails at the database.
    """

    @property
    def subscriptions(self) -> SubscriptionRepository: ...

    @property
    def markets(self) -> MarketPreferenceRepository: ...


# --- unit of work ----------------------------------------------------------


class MarketUnitOfWork(Protocol):
    def for_owner(self, owner_id: uuid.UUID) -> AbstractAsyncContextManager[OwnerMarket]: ...

    def shared(self) -> AbstractAsyncContextManager[SharedMarket]: ...

    def fanout(self) -> AbstractAsyncContextManager[FanoutMarket]: ...
