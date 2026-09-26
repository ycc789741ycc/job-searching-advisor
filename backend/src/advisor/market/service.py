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
    CompanySubscription,
    Coverage,
    CrawlSource,
    JobPosting,
    MarketSelected,
    MarketUnitOfWork,
    NormalizedPosting,
    PostingsChanged,
    PostingScope,
    PostingStatus,
    PrivateJobPosting,
    SalaryBand,
    SalaryRange,
    SharedMarket,
    SourceKind,
    SourceOrigin,
    SubscriptionAdded,
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


class CrawlIngest:
    """What the crawler may do. Shared zone only; no user data, ever."""

    def __init__(self, uow: MarketUnitOfWork) -> None:
        self._uow = uow

    async def due_sources(self) -> list[CrawlSourceView]:
        async with self._uow.shared() as market:
            return [
                CrawlSourceView(
                    id=due.source.id,
                    kind=due.source.kind,
                    endpoint=due.source.endpoint,
                    company_id=due.source.company_id,
                    company_name=due.company_name,
                    market=due.source.market,
                )
                for due in await market.sources.due()
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
            await market.sources.save(source)
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
            postings = await market.postings.needing_embeddings(model_name, limit)
        # Title carries most of the signal, so it leads, twice.
        return [(p.id, "\n".join(part for part in _embedding_parts(p) if part)) for p in postings]

    async def store_embeddings(
        self, model_name: str, vectors: dict[uuid.UUID, list[float]]
    ) -> None:
        async with self._uow.shared() as market:
            await market.postings.add_embeddings(model_name, vectors)


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
        async with self._uow.fanout() as watchers:
            if company_id is not None:
                affected |= await watchers.of_company(company_id)
            if market:
                affected |= await watchers.of_market(market)
        return sorted(affected)

    async def subscriptions(self, owner_id: uuid.UUID) -> list[CompanySubscriptionView]:
        async with self._uow.for_owner(owner_id) as mine:
            return [_subscription_view(s) for s in await mine.subscriptions.all()]

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
            subscription = await mine.subscriptions.find(company.id, title)
            if subscription is not None:
                subscription.resubscribe(role_id=role_id, url=link)
                await mine.subscriptions.save(subscription)
                return _subscription_view(subscription)

            # Coverage belongs to the company's board, so a new role at an
            # already-watched company starts from what is known about it.
            known = await mine.subscriptions.at_company(company.id)
            subscription = CompanySubscription.new(
                owner_id=owner_id,
                company=company,
                role_title=title,
                role_id=role_id,
                url=link,
                coverage=known[0].coverage if known else Coverage.MANUAL,
            )
            await mine.subscriptions.add(subscription)
            mine.record(
                SubscriptionAdded(
                    owner_id=owner_id, company_id=company.id, company_name=company.name
                )
            )
            return _subscription_view(subscription)

    async def set_coverage(
        self, owner_id: uuid.UUID, company_id: uuid.UUID, coverage: Coverage
    ) -> None:
        async with self._uow.for_owner(owner_id) as mine:
            await mine.subscriptions.set_coverage(company_id, coverage)

    async def mark_refreshed(self, owner_id: uuid.UUID, company_id: uuid.UUID) -> None:
        """Every role the user watches at this company shares its board, so a
        re-crawl refreshes them all."""
        async with self._uow.for_owner(owner_id) as mine:
            refreshed_at = utcnow()
            for subscription in await mine.subscriptions.at_company(company_id):
                subscription.last_refreshed_at = refreshed_at
                await mine.subscriptions.save(subscription)

    async def unsubscribe(self, owner_id: uuid.UUID, subscription_id: uuid.UUID) -> None:
        async with self._uow.for_owner(owner_id) as mine:
            await mine.subscriptions.remove(subscription_id)

    async def markets(self, owner_id: uuid.UUID) -> list[str]:
        async with self._uow.for_owner(owner_id) as mine:
            return await mine.markets.all()

    async def add_market(self, owner_id: uuid.UUID, market: str) -> list[str]:
        value = market.strip()
        if not value:
            raise ValidationError("a market is required")
        async with self._uow.for_owner(owner_id) as mine:
            if not await mine.markets.has(value):
                await mine.markets.add(value)
                mine.record(MarketSelected(owner_id=owner_id, market=value))
        return await self.markets(owner_id)

    async def remove_market(self, owner_id: uuid.UUID, market: str) -> list[str]:
        async with self._uow.for_owner(owner_id) as mine:
            await mine.markets.remove(market)
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
            match = await market.postings.by_canonical_key(key)

        posting = PrivateJobPosting(
            id=uuid.uuid4(),
            owner_id=owner_id,
            canonical_key=key,
            company_name=company_name.strip(),
            title=title.strip(),
            location=location,
            description=description,
            url=url,
            shared_posting_id=match.id if match is not None else None,
        )
        async with self._uow.for_owner(owner_id) as mine:
            await mine.private_postings.add(posting)
        return _private_posting_view(posting)

    async def private_postings(self, owner_id: uuid.UUID) -> list[PostingView]:
        async with self._uow.for_owner(owner_id) as mine:
            return [_private_posting_view(p) for p in await mine.private_postings.all()]

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
            shared = [
                _shared_posting_view(posting, company_name)
                for posting, company_name in await market.postings.open_in_scope(scope)
            ]

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
        shared_ids = [p.id for p in postings if p.visibility is Visibility.SHARED]

        vectors: dict[uuid.UUID, list[float]] = {}
        if shared_ids:
            async with self._uow.shared() as market:
                vectors = await market.postings.embeddings(shared_ids, model_name)

        async with self._uow.for_owner(owner_id) as mine:
            vectors.update(await mine.private_postings.vectors())

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
                await mine.private_postings.set_vector(posting_id, vector)

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
                source = await market.sources.by_kind_and_endpoint(listed.kind, listed.endpoint)
                if source is None:
                    await market.sources.add(
                        CrawlSource.board(
                            kind=listed.kind,
                            endpoint=listed.endpoint,
                            company_id=company.id,
                            origin=SourceOrigin.BASELINE,
                        )
                    )
                else:
                    source.make_baseline(company.id)
                    await market.sources.save(source)

            retired = 0
            for source in await market.sources.baseline():
                if (source.kind, source.endpoint) not in wanted and source.retire():
                    await market.sources.save(source)
                    retired += 1
        return len(sources), retired

    async def register_board(self, company_id: uuid.UUID, *, kind: str, endpoint: str) -> None:
        """Crawl a board found for a watched company, unless it is already known."""
        async with self._uow.shared() as market:
            if await market.sources.by_endpoint(endpoint) is None:
                await market.sources.add(
                    CrawlSource.board(
                        kind=kind,
                        endpoint=endpoint,
                        company_id=company_id,
                        origin=SourceOrigin.DEMAND,
                    )
                )

    async def watched_boards(self) -> list[tuple[uuid.UUID, str, str | None]]:
        """One entry per watched company, with the first link anyone gave for it.

        A cross-user read, through the fan-out transaction. Only the company and
        the link cross over — never who gave them — so the crawler holds no user
        data and cannot infer any.
        """
        async with self._uow.fanout() as watchers:
            boards = await watchers.watched_boards()
        by_company: dict[uuid.UUID, tuple[str, str | None]] = {}
        for company_id, company_name, url in boards:
            name, known_url = by_company.get(company_id, (company_name, None))
            by_company[company_id] = (name, known_url or url)
        return [(cid, name, url) for cid, (name, url) in by_company.items()]

    async def company_needing_source(self, company_id: uuid.UUID, fallback_name: str) -> str | None:
        """The name to look for a board under, or None when the company already
        has a crawl source."""
        async with self._uow.shared() as market:
            if await market.sources.exists_for_company(company_id):
                return None
            company = await market.companies.get(company_id)
            return company.name if company is not None else fallback_name

    async def add_demand_source(self, company_id: uuid.UUID, *, kind: str, endpoint: str) -> None:
        async with self._uow.shared() as market:
            await market.sources.add(
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
            used = await mine.refreshes.count_since(since)
            if not refresh_allowed(used_today=used, per_day=self._manual_refresh_per_day):
                raise RateLimitedError(
                    "you have used today's manual refreshes; the weekly crawl still runs",
                    limit=self._manual_refresh_per_day,
                )
            await mine.refreshes.record(company_id)

    async def salary_band(self, owner_id: uuid.UUID, posting_ids: list[uuid.UUID]) -> object:
        async with self._uow.shared() as market:
            ranges = await market.postings.salary_ranges(posting_ids)
        return band_from([(r.min_amount, r.max_amount, r.currency) for r in ranges])


# --- helpers ---------------------------------------------------------------


async def _ensure_company(market: SharedMarket, name: str) -> Company:
    company = await market.companies.by_normalized_name(normalize(name))
    if company is None:
        company = Company.named(name)
        await market.companies.add(company)
    return company


async def _upsert_posting(
    market: SharedMarket,
    source_id: uuid.UUID,
    company_id: uuid.UUID,
    posting: NormalizedPosting,
) -> None:
    now = utcnow()
    existing = await market.postings.by_canonical_key(posting.canonical_key)
    if existing is None:
        await market.postings.add(
            JobPosting.first_seen(posting, company_id=company_id, source_id=source_id, at=now)
        )
        return
    existing.seen_again(posting, source_id=source_id, at=now)
    await market.postings.save(existing)


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
