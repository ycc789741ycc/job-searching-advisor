"""Companies, postings and crawl sources.

Two audiences with very different rights:

* ``MarketService`` — api and worker. Owner-zone reads and writes.
* ``CrawlIngest`` — the crawler deployable. Shared zone only. Its unit of work
  runs on the ``crawler_rw`` role, which has no grant on any user schema, so a
  mistake here fails at the database rather than leaking.

Both reach stored data only through the repository interfaces in
``advisor.market.domain`` (ADR 0010).

The domain value objects the crawler needs are re-exported here, because the
crawler may not import ``advisor.market.domain`` directly.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from advisor.market.baseline import BASELINE_SOURCES, BaselineSource
from advisor.market.domain import (
    Company,
    CompanyFilter,
    CompanySubscription,
    Coverage,
    CrawlSource,
    CrawlSourceFilter,
    JobPosting,
    JobPostingFilter,
    ManualRefresh,
    ManualRefreshFilter,
    MarketPreference,
    MarketPreferenceFilter,
    MarketSelected,
    MarketUnitOfWork,
    NormalizedPosting,
    PostingEmbedding,
    PostingEmbeddingFilter,
    PostingsChanged,
    PostingScope,
    PostingStatus,
    PrivateJobPosting,
    PrivateJobPostingFilter,
    SalaryBand,
    SalaryRange,
    SharedMarket,
    SourceKind,
    SourceOrigin,
    SourceStatus,
    SubscriptionAdded,
    SubscriptionFilter,
    Visibility,
    band_from,
    canonical_key,
    normalize,
    refresh_allowed,
)
from kernel.clock import utcnow
from kernel.errors import NotFoundError, RateLimitedError, ValidationError

__all__ = [
    "BASELINE_SOURCES",
    "BaselineSource",
    "CompanySubscriptionView",
    "Coverage",
    "CrawlIngest",
    "CrawlSourceView",
    "MarketService",
    "NormalizedPosting",
    "PostingStatus",
    "PostingView",
    "SalaryBand",
    "SalaryRange",
    "SourceKind",
    "SourceOrigin",
    "Visibility",
    "band_from",
    "canonical_key",
]


@dataclass(frozen=True, slots=True)
class CrawlSourceView:
    id: uuid.UUID
    kind: str
    endpoint: str
    company_id: uuid.UUID | None
    company_name: str | None
    market: str | None


@dataclass(frozen=True, slots=True)
class CompanySubscriptionView:
    """A RoleSubscription: one role at one company (domain decision 19)."""

    id: uuid.UUID
    company_id: uuid.UUID
    company_name: str
    role_title: str
    role_id: uuid.UUID | None
    url: str | None
    coverage: Coverage
    last_refreshed_at: datetime | None


@dataclass(frozen=True, slots=True)
class PostingView:
    id: uuid.UUID
    company_name: str
    title: str
    location: str | None
    url: str | None
    description: str
    visibility: Visibility
    salary: SalaryRange | None
    # Shared postings only; a pasted JD names its company but has no row there.
    company_id: uuid.UUID | None = None
    # Which kind of source it was crawled from (atsBoard, jsonLd, publicApi);
    # None for a pasted JD, which was not crawled at all.
    source_kind: str | None = None


# The fan-out reads every user's subscriptions; it pages through them rather
# than loading a table that grows with the user base in one go.
_FANOUT_PAGE_SIZE = 500


class CrawlIngest:
    """What the crawler may do. Shared zone only; no user data, ever."""

    def __init__(self, uow: MarketUnitOfWork) -> None:
        self._uow = uow

    async def due_sources(self) -> list[CrawlSourceView]:
        async with self._uow.shared() as market:
            # Every active source is crawled each run, so the set is read whole.
            sources = await market.sources.get_list(CrawlSourceFilter(status=SourceStatus.ACTIVE))
            names = await _company_names(market, {s.company_id for s in sources})
        return [
            CrawlSourceView(
                id=source.id,
                kind=source.kind,
                endpoint=source.endpoint,
                company_id=source.company_id,
                company_name=names.get(source.company_id) if source.company_id else None,
                market=source.market,
            )
            for source in sources
        ]

    async def record_crawl(
        self,
        source_id: uuid.UUID,
        postings: list[NormalizedPosting],
        *,
        error: str | None = None,
    ) -> tuple[int, int]:
        """Upsert what was seen, expire what was not. Returns (upserted, expired)."""
        async with self._uow.shared() as market:
            source = await market.sources.get(source_id)
            if source is None:
                raise NotFoundError("crawl source not found", source_id=str(source_id))
            source.record_fetch(utcnow(), error)
            await market.sources.update(source)
            if error is not None:
                return (0, 0)

            seen_keys: set[str] = set()
            for posting in postings:
                company = await _ensure_company(market, posting.company_name)
                await _upsert_posting(market, source_id, company.id, posting)
                seen_keys.add(posting.canonical_key)

            expired = await market.postings.expire_unseen(source_id, seen_keys)

            market.record(
                PostingsChanged(
                    company_id=source.company_id,
                    market=source.market,
                    seen=len(seen_keys),
                    expired=expired,
                )
            )
            return (len(seen_keys), expired)

    async def postings_needing_embeddings(
        self, model_name: str, limit: int = 200
    ) -> list[tuple[uuid.UUID, str]]:
        async with self._uow.shared() as market:
            postings = await market.postings.get_list(
                JobPostingFilter(missing_embedding_for=model_name), page_size=limit
            )
        # Title carries most of the signal, so it leads, twice.
        return [(p.id, "\n".join(part for part in _embedding_parts(p) if part)) for p in postings]

    async def store_embeddings(
        self, model_name: str, vectors: dict[uuid.UUID, list[float]]
    ) -> None:
        async with self._uow.shared() as market:
            for posting_id, vector in vectors.items():
                await market.embeddings.create(
                    PostingEmbedding(posting_id=posting_id, model_name=model_name, vector=vector)
                )


class MarketService:
    """Subscriptions, market preferences and pasted JDs. Owner zone."""

    def __init__(self, uow: MarketUnitOfWork, *, manual_refresh_per_day: int) -> None:
        self._uow = uow
        self._manual_refresh_per_day = manual_refresh_per_day

    async def owners_affected_by(
        self, *, company_id: uuid.UUID | None = None, market: str | None = None
    ) -> list[uuid.UUID]:
        """The users who watch this company or this market.

        The only cross-user read in the system, through the fan-out transaction
        and its SELECT-only policy. The crawler cannot answer this — it has no
        grant on any user schema — so the worker's dispatcher asks here when a
        market changes (docs/technical_boundaries.md section 2).
        """
        affected: set[uuid.UUID] = set()
        async with self._uow.fanout() as everyone:
            if company_id is not None:
                watching = await everyone.subscriptions.get_list(
                    SubscriptionFilter(company_id=company_id)
                )
                affected |= {s.owner_id for s in watching}
            if market:
                choosing = await everyone.markets.get_list(MarketPreferenceFilter(market=market))
                affected |= {m.owner_id for m in choosing}
        return sorted(affected)

    async def subscriptions(self, owner_id: uuid.UUID) -> list[CompanySubscriptionView]:
        """Newest first. One user's watches: a small set, read whole."""
        async with self._uow.for_owner(owner_id) as mine:
            return [
                _subscription_view(s)
                for s in await mine.subscriptions.get_list(SubscriptionFilter())
            ]

    async def subscription(
        self, owner_id: uuid.UUID, subscription_id: uuid.UUID
    ) -> CompanySubscriptionView:
        async with self._uow.for_owner(owner_id) as mine:
            subscription = await mine.subscriptions.get(subscription_id)
            if subscription is None:
                raise NotFoundError("subscription not found", subscription_id=str(subscription_id))
            return _subscription_view(subscription)

    async def subscribe(
        self,
        owner_id: uuid.UUID,
        *,
        company_name: str,
        role_title: str,
        role_id: uuid.UUID | None = None,
        url: str | None = None,
    ) -> CompanySubscriptionView:
        """Watch one role at one company. Subscribing again to the same role
        there updates its link rather than adding a duplicate."""
        name = company_name.strip()
        if not name:
            raise ValidationError("a company name is required")
        title = role_title.strip()
        if not title:
            raise ValidationError("a role is required")
        link = (url or "").strip() or None
        if link is not None and not link.lower().startswith(("https://", "http://")):
            raise ValidationError("a link must start with http:// or https://")

        async with self._uow.shared() as market:
            company = await _ensure_company(market, name)

        async with self._uow.for_owner(owner_id) as mine:
            existing = _first(
                await mine.subscriptions.get_list(
                    SubscriptionFilter(company_id=company.id, role_title=title), page_size=1
                )
            )
            if existing is not None:
                existing.resubscribe(role_id=role_id, url=link)
                return _subscription_view(await mine.subscriptions.update(existing))

            # Coverage belongs to the company's board, so a new role at an
            # already-watched company starts from what is known about it.
            known = _first(
                await mine.subscriptions.get_list(
                    SubscriptionFilter(company_id=company.id), page_size=1
                )
            )
            created = await mine.subscriptions.create(
                CompanySubscription.new(
                    owner_id=owner_id,
                    company=company,
                    role_title=title,
                    role_id=role_id,
                    url=link,
                    coverage=known.coverage if known is not None else Coverage.MANUAL,
                )
            )
            mine.record(
                SubscriptionAdded(
                    owner_id=owner_id, company_id=company.id, company_name=company.name
                )
            )
            return _subscription_view(created)

    async def set_coverage(
        self, owner_id: uuid.UUID, company_id: uuid.UUID, coverage: Coverage
    ) -> None:
        """Coverage belongs to the company's board, so every role watched there
        takes it at once."""
        async with self._uow.for_owner(owner_id) as mine:
            for subscription in await mine.subscriptions.get_list(
                SubscriptionFilter(company_id=company_id)
            ):
                subscription.coverage = coverage
                await mine.subscriptions.update(subscription)

    async def mark_refreshed(self, owner_id: uuid.UUID, company_id: uuid.UUID) -> None:
        """Every role the user watches at this company shares its board, so a
        re-crawl refreshes them all."""
        async with self._uow.for_owner(owner_id) as mine:
            refreshed_at = utcnow()
            for subscription in await mine.subscriptions.get_list(
                SubscriptionFilter(company_id=company_id)
            ):
                subscription.last_refreshed_at = refreshed_at
                await mine.subscriptions.update(subscription)

    async def unsubscribe(self, owner_id: uuid.UUID, subscription_id: uuid.UUID) -> None:
        """Idempotent: an unknown or someone else's subscription is left alone."""
        async with self._uow.for_owner(owner_id) as mine:
            if await mine.subscriptions.get(subscription_id) is not None:
                await mine.subscriptions.delete(subscription_id)

    async def markets(self, owner_id: uuid.UUID) -> list[str]:
        async with self._uow.for_owner(owner_id) as mine:
            chosen = await mine.markets.get_list(MarketPreferenceFilter())
        return sorted(m.market for m in chosen)

    async def add_market(self, owner_id: uuid.UUID, market: str) -> list[str]:
        value = market.strip()
        if not value:
            raise ValidationError("a market is required")
        async with self._uow.for_owner(owner_id) as mine:
            if await mine.markets.get_count(MarketPreferenceFilter(market=value)) == 0:
                await mine.markets.create(MarketPreference.chosen(owner_id=owner_id, market=value))
                mine.record(MarketSelected(owner_id=owner_id, market=value))
        return await self.markets(owner_id)

    async def remove_market(self, owner_id: uuid.UUID, market: str) -> list[str]:
        async with self._uow.for_owner(owner_id) as mine:
            for preference in await mine.markets.get_list(MarketPreferenceFilter(market=market)):
                await mine.markets.delete(preference.id)
        return await self.markets(owner_id)

    async def paste_job_description(
        self,
        owner_id: uuid.UUID,
        *,
        company_name: str,
        title: str,
        location: str | None,
        description: str,
        url: str | None = None,
    ) -> PostingView:
        """Store a JD the user pasted. Private to them, always."""
        if not description.strip():
            raise ValidationError("a job description is required")
        if not title.strip():
            raise ValidationError("a job title is required")

        key = canonical_key(company=company_name, title=title, location=location)

        # A private copy may link to a matching crawled posting so the user gets
        # weekly updates. Nothing flows back the other way.
        async with self._uow.shared() as market:
            match = _first(
                await market.postings.get_list(JobPostingFilter(canonical_key=key), page_size=1)
            )

        async with self._uow.for_owner(owner_id) as mine:
            created = await mine.private_postings.create(
                PrivateJobPosting.pasted(
                    owner_id=owner_id,
                    company_name=company_name,
                    title=title,
                    location=location,
                    description=description,
                    url=url,
                    shared_posting_id=match.id if match is not None else None,
                )
            )
        return _private_posting_view(created)

    async def private_postings(self, owner_id: uuid.UUID) -> list[PostingView]:
        """Newest first. One user's pasted JDs: a small set, read whole."""
        async with self._uow.for_owner(owner_id) as mine:
            pasted = await mine.private_postings.get_list(PrivateJobPostingFilter())
        return [_private_posting_view(p) for p in pasted]

    async def private_posting(self, owner_id: uuid.UUID, posting_id: uuid.UUID) -> PostingView:
        """One pasted JD. Another user's is simply not found: it is behind RLS."""
        async with self._uow.for_owner(owner_id) as mine:
            posting = await mine.private_postings.get(posting_id)
            if posting is None:
                raise NotFoundError("job description not found", posting_id=str(posting_id))
            return _private_posting_view(posting)

    async def postings_in_scope(self, owner_id: uuid.UUID) -> list[PostingView]:
        """Every posting this user's role map is built from.

        Shared postings in their markets or from a company they watch, plus
        their own pasted JDs. A user who has chosen no market also gets the
        platform's baseline postings (domain decision 15), so a first role map
        has something to group. Another user's private postings can never
        appear here — they are in a schema this query does not touch.
        """
        markets = await self.markets(owner_id)
        subscriptions = await self.subscriptions(owner_id)
        scope = PostingScope(
            company_ids=tuple(s.company_id for s in subscriptions), markets=tuple(markets)
        )

        async with self._uow.shared() as market:
            postings = await market.postings.get_open_in_scope(scope)
            names = await _company_names(market, {p.company_id for p in postings})

        shared = [_shared_posting_view(p, names.get(p.company_id, "")) for p in postings]
        return shared + await self.private_postings(owner_id)

    async def scope_with_vectors(
        self, owner_id: uuid.UUID, model_name: str
    ) -> list[tuple[str, PostingView, list[float] | None]]:
        """Every posting in this user's scope, with its embedding where one exists.

        Shared postings were embedded by the crawler. Pasted JDs have not been,
        so they come back with ``None`` and the caller embeds them — that stays
        platform-paid computation, never the user's key.

        The key is the posting's stable identity for clustering: the shared id,
        or ``private:<id>`` for a pasted JD.
        """
        postings = await self.postings_in_scope(owner_id)
        shared_ids = tuple(p.id for p in postings if p.visibility is Visibility.SHARED)

        vectors: dict[uuid.UUID, list[float]] = {}
        if shared_ids:
            async with self._uow.shared() as market:
                embedded = await market.embeddings.get_list(
                    PostingEmbeddingFilter(posting_ids=shared_ids, model_name=model_name)
                )
            vectors = {e.posting_id: e.vector for e in embedded}

        async with self._uow.for_owner(owner_id) as mine:
            for pasted in await mine.private_postings.get_list(
                PrivateJobPostingFilter(has_vector=True)
            ):
                if pasted.vector is not None:
                    vectors[pasted.id] = pasted.vector

        return [
            (
                f"private:{p.id}" if p.visibility is Visibility.PRIVATE else str(p.id),
                p,
                vectors.get(p.id),
            )
            for p in postings
        ]

    async def store_private_vectors(
        self, owner_id: uuid.UUID, vectors: dict[uuid.UUID, list[float]]
    ) -> None:
        async with self._uow.for_owner(owner_id) as mine:
            for posting_id, vector in vectors.items():
                pasted = await mine.private_postings.get(posting_id)
                if pasted is not None:
                    pasted.vector = vector
                    await mine.private_postings.update(pasted)

    async def seed_baseline(
        self, sources: tuple[BaselineSource, ...] = BASELINE_SOURCES
    ) -> tuple[int, int]:
        """Make ``market.crawl_source`` match the baseline list. Idempotent.

        Returns (active, retired). An entry no longer listed is retired, never
        deleted: the postings it found keep a source that can expire them.
        A demand source with the same endpoint becomes a baseline one; it is
        the same board either way.
        """
        wanted = {(s.kind, s.endpoint) for s in sources}
        async with self._uow.shared() as market:
            for listed in sources:
                company = await _ensure_company(market, listed.company_name)
                source = _first(
                    await market.sources.get_list(
                        CrawlSourceFilter(kind=listed.kind, endpoint=listed.endpoint), page_size=1
                    )
                )
                if source is None:
                    await market.sources.create(
                        CrawlSource.board(
                            kind=listed.kind,
                            endpoint=listed.endpoint,
                            company_id=company.id,
                            origin=SourceOrigin.BASELINE,
                        )
                    )
                else:
                    source.make_baseline(company.id)
                    await market.sources.update(source)

            retired = 0
            # The baseline list is short by design (see advisor.market.baseline).
            for source in await market.sources.get_list(
                CrawlSourceFilter(origin=SourceOrigin.BASELINE)
            ):
                if (source.kind, source.endpoint) not in wanted and source.retire():
                    await market.sources.update(source)
                    retired += 1
        return len(sources), retired

    async def register_board(self, company_id: uuid.UUID, *, kind: str, endpoint: str) -> None:
        """Crawl a board found for a watched company, unless it is already known."""
        async with self._uow.shared() as market:
            if await market.sources.get_count(CrawlSourceFilter(endpoint=endpoint)) == 0:
                await market.sources.create(
                    CrawlSource.board(
                        kind=kind,
                        endpoint=endpoint,
                        company_id=company_id,
                        origin=SourceOrigin.DEMAND,
                    )
                )

    async def watched_boards(self) -> list[tuple[uuid.UUID, str, str | None]]:
        """One entry per watched company, with a link someone gave for it.

        A cross-user read, through the fan-out transaction. Only the company and
        the link cross over — never who gave them — so the crawler holds no user
        data and cannot infer any.
        """
        by_company: dict[uuid.UUID, tuple[str, str | None]] = {}
        async with self._uow.fanout() as everyone:
            page = 1
            while True:
                batch = await everyone.subscriptions.get_list(
                    SubscriptionFilter(), page=page, page_size=_FANOUT_PAGE_SIZE
                )
                for s in batch:
                    name, known_url = by_company.get(s.company_id, (s.company_name, None))
                    by_company[s.company_id] = (name, known_url or s.url)
                if len(batch) < _FANOUT_PAGE_SIZE:
                    break
                page += 1
        return [(cid, name, url) for cid, (name, url) in by_company.items()]

    async def company_needing_source(self, company_id: uuid.UUID, fallback_name: str) -> str | None:
        """The name to look for a board under, or None when the company already
        has a crawl source."""
        async with self._uow.shared() as market:
            if await market.sources.get_count(CrawlSourceFilter(company_id=company_id)) > 0:
                return None
            company = await market.companies.get(company_id)
            return company.name if company is not None else fallback_name

    async def add_demand_source(self, company_id: uuid.UUID, *, kind: str, endpoint: str) -> None:
        async with self._uow.shared() as market:
            await market.sources.create(
                CrawlSource.board(
                    kind=kind, endpoint=endpoint, company_id=company_id, origin=SourceOrigin.DEMAND
                )
            )

    async def request_manual_refresh(self, owner_id: uuid.UUID, company_id: uuid.UUID) -> None:
        """Re-crawl one watched company now, within a per-day cap.

        The weekly schedule stays the norm; this is for the moment right after
        subscribing.
        """
        since = utcnow() - timedelta(days=1)
        async with self._uow.for_owner(owner_id) as mine:
            used = await mine.refreshes.get_count(ManualRefreshFilter(requested_since=since))
            if not refresh_allowed(used_today=used, per_day=self._manual_refresh_per_day):
                raise RateLimitedError(
                    "you have used today's manual refreshes; the weekly crawl still runs",
                    limit=self._manual_refresh_per_day,
                )
            await mine.refreshes.create(
                ManualRefresh.requested(owner_id=owner_id, company_id=company_id)
            )

    async def salary_band(self, owner_id: uuid.UUID, posting_ids: list[uuid.UUID]) -> object:
        async with self._uow.shared() as market:
            paying = await market.postings.get_list(
                JobPostingFilter(ids=tuple(posting_ids), has_salary=True)
            )
        ranges = [p.salary for p in paying if p.salary is not None]
        return band_from([(r.min_amount, r.max_amount, r.currency) for r in ranges])


# --- helpers ---------------------------------------------------------------


def _first[T](items: list[T]) -> T | None:
    return items[0] if items else None


async def _company_names(
    market: SharedMarket, company_ids: set[uuid.UUID | None]
) -> dict[uuid.UUID, str]:
    ids = tuple(i for i in company_ids if i is not None)
    if not ids:
        return {}
    companies = await market.companies.get_list(CompanyFilter(ids=ids))
    return {c.id: c.name for c in companies}


async def _ensure_company(market: SharedMarket, name: str) -> Company:
    existing = _first(
        await market.companies.get_list(CompanyFilter(normalized_name=normalize(name)), page_size=1)
    )
    if existing is not None:
        return existing
    return await market.companies.create(Company.named(name))


async def _upsert_posting(
    market: SharedMarket,
    source_id: uuid.UUID,
    company_id: uuid.UUID,
    posting: NormalizedPosting,
) -> None:
    now = utcnow()
    existing = _first(
        await market.postings.get_list(
            JobPostingFilter(canonical_key=posting.canonical_key), page_size=1
        )
    )
    if existing is None:
        await market.postings.create(
            JobPosting.first_seen(posting, company_id=company_id, source_id=source_id, at=now)
        )
        return
    existing.seen_again(posting, source_id=source_id, at=now)
    await market.postings.update(existing)


def _embedding_parts(posting: JobPosting) -> tuple[str | None, ...]:
    return (posting.title, posting.title, posting.location, posting.description)


def _subscription_view(subscription: CompanySubscription) -> CompanySubscriptionView:
    return CompanySubscriptionView(
        id=subscription.id,
        company_id=subscription.company_id,
        company_name=subscription.company_name,
        role_title=subscription.role_title,
        role_id=subscription.role_id,
        url=subscription.url,
        coverage=subscription.coverage,
        last_refreshed_at=subscription.last_refreshed_at,
    )


def _shared_posting_view(posting: JobPosting, company_name: str) -> PostingView:
    return PostingView(
        id=posting.id,
        company_name=company_name,
        title=posting.title,
        location=posting.location,
        url=posting.url,
        description=posting.description,
        visibility=Visibility.SHARED,
        salary=posting.salary,
        company_id=posting.company_id,
        source_kind=posting.source_kind,
    )


def _private_posting_view(posting: PrivateJobPosting) -> PostingView:
    return PostingView(
        id=posting.id,
        company_name=posting.company_name,
        title=posting.title,
        location=posting.location,
        url=posting.url,
        description=posting.description,
        visibility=Visibility.PRIVATE,
        salary=None,
    )
