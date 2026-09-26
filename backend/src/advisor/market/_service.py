"""Companies, postings and crawl sources.

Two audiences with very different rights:

* ``MarketService`` — api and worker. Owner-zone reads and writes.
* ``CrawlIngest`` — the crawler deployable. Shared zone only. It is given a
  session built from the ``crawler_rw`` role, which has no grant on any user
  schema, so a mistake here fails at the database rather than leaking.

The domain value objects the crawler needs are re-exported here, because the
crawler may not import ``advisor.market._domain`` directly.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from advisor.market._baseline import BASELINE_SOURCES, BaselineSource
from advisor.market._domain import (
    Coverage,
    NormalizedPosting,
    PostingStatus,
    SalaryBand,
    SalaryRange,
    SourceKind,
    SourceOrigin,
    Visibility,
    band_from,
    canonical_key,
    normalize,
)
from advisor.market._infra.models import (
    Company,
    CompanySubscription,
    CrawlSource,
    JobPosting,
    ManualRefreshLog,
    MarketPreference,
    PostingEmbedding,
    PrivateJobPosting,
)
from kernel.db import Database
from kernel.db.base import utcnow
from kernel.errors import NotFoundError, RateLimitedError, ValidationError
from kernel.outbox import EventName, emit

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

    def __init__(self, database: Database) -> None:
        self._db = database

    async def due_sources(self) -> list[CrawlSourceView]:
        async with self._db.shared() as session:
            rows = await session.execute(
                select(CrawlSource, Company.name)
                .outerjoin(Company, CrawlSource.company_id == Company.id)
                .where(CrawlSource.status == "active")
            )
            return [
                CrawlSourceView(
                    id=source.id,
                    kind=source.kind,
                    endpoint=source.endpoint,
                    company_id=source.company_id,
                    company_name=company_name,
                    market=source.market,
                )
                for source, company_name in rows.all()
            ]

    async def record_crawl(
        self,
        source_id: uuid.UUID,
        postings: list[NormalizedPosting],
        *,
        error: str | None = None,
    ) -> tuple[int, int]:
        """Upsert what was seen, expire what was not. Returns (upserted, expired)."""
        async with self._db.shared() as session:
            source = await session.get(CrawlSource, source_id)
            if source is None:
                raise NotFoundError("crawl source not found", source_id=str(source_id))
            source.last_fetched_at = utcnow()
            source.last_error = error
            if error is not None:
                return (0, 0)

            seen_keys: set[str] = set()
            for posting in postings:
                company = await _ensure_company(session, posting.company_name)
                await _upsert_posting(session, source_id, company.id, posting)
                seen_keys.add(posting.canonical_key)

            expired = await _expire_unseen(session, source_id, seen_keys)

            await emit(
                session,
                EventName.POSTINGS_CHANGED,
                {
                    # Markets and companies only. The crawler must not work out
                    # which users are affected — the dispatcher fans that out.
                    "company_id": str(source.company_id) if source.company_id else None,
                    "market": source.market,
                    "seen": len(seen_keys),
                    "expired": expired,
                },
            )
            return (len(seen_keys), expired)

    async def postings_needing_embeddings(
        self, model_name: str, limit: int = 200
    ) -> list[tuple[uuid.UUID, str]]:
        async with self._db.shared() as session:
            rows = await session.execute(
                select(JobPosting.id, JobPosting.title, JobPosting.location, JobPosting.description)
                .outerjoin(
                    PostingEmbedding,
                    (PostingEmbedding.job_posting_id == JobPosting.id)
                    & (PostingEmbedding.model_name == model_name),
                )
                .where(PostingEmbedding.job_posting_id.is_(None))
                .limit(limit)
            )
            return [
                (
                    row.id,
                    "\n".join(
                        part
                        for part in (row.title, row.title, row.location, row.description)
                        if part
                    ),
                )
                for row in rows.all()
            ]

    async def store_embeddings(
        self, model_name: str, vectors: dict[uuid.UUID, list[float]]
    ) -> None:
        async with self._db.shared() as session:
            for posting_id, vector in vectors.items():
                session.add(
                    PostingEmbedding(
                        job_posting_id=posting_id, model_name=model_name, vector=vector
                    )
                )


class MarketService:
    """Subscriptions, market preferences and pasted JDs. Owner zone."""

    def __init__(self, database: Database, *, manual_refresh_per_day: int) -> None:
        self._db = database
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
        async with self._db.fanout() as session:
            if company_id is not None:
                rows = await session.execute(
                    select(CompanySubscription.owner_id)
                    .where(CompanySubscription.company_id == company_id)
                    .distinct()
                )
                affected.update(rows.scalars())
            if market:
                rows = await session.execute(
                    select(MarketPreference.owner_id)
                    .where(MarketPreference.market == market)
                    .distinct()
                )
                affected.update(rows.scalars())
        return sorted(affected)

    async def subscriptions(self, owner_id: uuid.UUID) -> list[CompanySubscriptionView]:
        async with self._db.for_user(owner_id) as session:
            rows = await session.execute(
                select(CompanySubscription).where(CompanySubscription.owner_id == owner_id)
            )
            return [_subscription_view(row) for row in rows.scalars()]

    async def subscription(
        self, owner_id: uuid.UUID, subscription_id: uuid.UUID
    ) -> CompanySubscriptionView:
        async with self._db.for_user(owner_id) as session:
            row = await session.get(CompanySubscription, subscription_id)
            if row is None or row.owner_id != owner_id:
                raise NotFoundError("subscription not found", subscription_id=str(subscription_id))
            return _subscription_view(row)

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

        async with self._db.shared() as shared:
            company = await _ensure_company(shared, name)
            company_id, resolved_name = company.id, company.name

        async with self._db.for_user(owner_id) as session:
            existing = await session.execute(
                select(CompanySubscription).where(
                    CompanySubscription.owner_id == owner_id,
                    CompanySubscription.company_id == company_id,
                    CompanySubscription.role_title == title,
                )
            )
            subscription = existing.scalar_one_or_none()
            if subscription is not None:
                subscription.role_id = role_id or subscription.role_id
                subscription.url = link or subscription.url
                await session.flush()
            else:
                # Coverage belongs to the company's board, so a new role at an
                # already-watched company starts from what is known about it.
                known = await session.execute(
                    select(CompanySubscription.coverage).where(
                        CompanySubscription.owner_id == owner_id,
                        CompanySubscription.company_id == company_id,
                    )
                )
                coverage = known.scalars().first() or str(Coverage.MANUAL)
                subscription = CompanySubscription(
                    owner_id=owner_id,
                    company_id=company_id,
                    company_name=resolved_name,
                    role_title=title,
                    role_id=role_id,
                    url=link,
                    coverage=coverage,
                )
                session.add(subscription)
                await session.flush()
                await emit(
                    session,
                    EventName.SUBSCRIPTION_ADDED,
                    {"company_id": str(company_id), "company_name": resolved_name},
                    owner_id=owner_id,
                )
            return _subscription_view(subscription)

    async def set_coverage(
        self, owner_id: uuid.UUID, company_id: uuid.UUID, coverage: Coverage
    ) -> None:
        async with self._db.for_user(owner_id) as session:
            await session.execute(
                update(CompanySubscription)
                .where(
                    CompanySubscription.owner_id == owner_id,
                    CompanySubscription.company_id == company_id,
                )
                .values(coverage=str(coverage))
            )

    async def unsubscribe(self, owner_id: uuid.UUID, subscription_id: uuid.UUID) -> None:
        async with self._db.for_user(owner_id) as session:
            subscription = await session.get(CompanySubscription, subscription_id)
            if subscription is not None and subscription.owner_id == owner_id:
                await session.delete(subscription)

    async def markets(self, owner_id: uuid.UUID) -> list[str]:
        async with self._db.for_user(owner_id) as session:
            rows = await session.execute(
                select(MarketPreference.market).where(MarketPreference.owner_id == owner_id)
            )
            return sorted(rows.scalars())

    async def add_market(self, owner_id: uuid.UUID, market: str) -> list[str]:
        value = market.strip()
        if not value:
            raise ValidationError("a market is required")
        async with self._db.for_user(owner_id) as session:
            existing = await session.execute(
                select(MarketPreference).where(
                    MarketPreference.owner_id == owner_id, MarketPreference.market == value
                )
            )
            if existing.scalar_one_or_none() is None:
                session.add(MarketPreference(owner_id=owner_id, market=value))
                await emit(session, EventName.MARKET_SELECTED, {"market": value}, owner_id=owner_id)
        return await self.markets(owner_id)

    async def remove_market(self, owner_id: uuid.UUID, market: str) -> list[str]:
        async with self._db.for_user(owner_id) as session:
            rows = await session.execute(
                select(MarketPreference).where(
                    MarketPreference.owner_id == owner_id, MarketPreference.market == market
                )
            )
            preference = rows.scalar_one_or_none()
            if preference is not None:
                await session.delete(preference)
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
        async with self._db.shared() as shared:
            match = await shared.execute(
                select(JobPosting.id).where(JobPosting.canonical_key == key)
            )
            shared_posting_id = match.scalar_one_or_none()

        async with self._db.for_user(owner_id) as session:
            posting = PrivateJobPosting(
                owner_id=owner_id,
                canonical_key=key,
                company_name=company_name.strip(),
                title=title.strip(),
                location=location,
                description=description,
                url=url,
                shared_posting_id=shared_posting_id,
            )
            session.add(posting)
            await session.flush()
            return _private_posting_view(posting)

    async def private_postings(self, owner_id: uuid.UUID) -> list[PostingView]:
        async with self._db.for_user(owner_id) as session:
            rows = await session.execute(
                select(PrivateJobPosting).where(PrivateJobPosting.owner_id == owner_id)
            )
            return [_private_posting_view(row) for row in rows.scalars()]

    async def private_posting(self, owner_id: uuid.UUID, posting_id: uuid.UUID) -> PostingView:
        """One pasted JD. Another user's is simply not found: it is behind RLS."""
        async with self._db.for_user(owner_id) as session:
            row = await session.get(PrivateJobPosting, posting_id)
            if row is None or row.owner_id != owner_id:
                raise NotFoundError("job description not found", posting_id=str(posting_id))
            return _private_posting_view(row)

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
        company_ids = [s.company_id for s in subscriptions]

        async with self._db.shared() as session:
            query = (
                select(JobPosting, Company.name)
                .join(Company, JobPosting.company_id == Company.id)
                .where(JobPosting.status == str(PostingStatus.OPEN))
            )
            conditions: list[ColumnElement[bool]] = []
            if company_ids:
                conditions.append(JobPosting.company_id.in_(company_ids))
            if markets:
                conditions.append(JobPosting.location.in_(markets))
            else:
                # With markets chosen, baseline postings in them are already
                # in scope through the location match above.
                conditions.append(
                    JobPosting.crawl_source_id.in_(
                        select(CrawlSource.id).where(
                            CrawlSource.origin == str(SourceOrigin.BASELINE)
                        )
                    )
                )
            query = query.where(_any_of(conditions))
            rows = await session.execute(query)
            shared_rows = [
                _shared_posting_view(posting, company_name) for posting, company_name in rows.all()
            ]

        return shared_rows + await self.private_postings(owner_id)

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
            async with self._db.shared() as session:
                rows = await session.execute(
                    select(PostingEmbedding.job_posting_id, PostingEmbedding.vector).where(
                        PostingEmbedding.job_posting_id.in_(shared_ids),
                        PostingEmbedding.model_name == model_name,
                    )
                )
                vectors = {row[0]: list(row[1]) for row in rows.all()}

        async with self._db.for_user(owner_id) as session:
            private_rows = await session.execute(
                select(PrivateJobPosting.id, PrivateJobPosting.vector).where(
                    PrivateJobPosting.owner_id == owner_id,
                    PrivateJobPosting.vector.is_not(None),
                )
            )
            for posting_id, vector in private_rows.all():
                vectors[posting_id] = list(vector)

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
        async with self._db.for_user(owner_id) as session:
            for posting_id, vector in vectors.items():
                posting = await session.get(PrivateJobPosting, posting_id)
                if posting is not None and posting.owner_id == owner_id:
                    posting.vector = vector

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
        async with self._db.shared() as session:
            for source in sources:
                company = await _ensure_company(session, source.company_name)
                existing = await session.execute(
                    select(CrawlSource).where(
                        CrawlSource.kind == source.kind, CrawlSource.endpoint == source.endpoint
                    )
                )
                row = existing.scalar_one_or_none()
                if row is None:
                    session.add(
                        CrawlSource(
                            kind=source.kind,
                            company_id=company.id,
                            endpoint=source.endpoint,
                            origin=str(SourceOrigin.BASELINE),
                        )
                    )
                else:
                    row.origin = str(SourceOrigin.BASELINE)
                    row.status = "active"
                    row.company_id = row.company_id or company.id

            listed = await session.execute(
                select(CrawlSource).where(CrawlSource.origin == str(SourceOrigin.BASELINE))
            )
            retired = 0
            for row in listed.scalars():
                if (row.kind, row.endpoint) not in wanted and row.status != "retired":
                    row.status = "retired"
                    retired += 1
        return len(sources), retired

    async def request_manual_refresh(self, owner_id: uuid.UUID, company_id: uuid.UUID) -> None:
        """Re-crawl one watched company now, within a per-day cap.

        The weekly schedule stays the norm; this is for the moment right after
        subscribing.
        """
        since = utcnow() - timedelta(days=1)
        async with self._db.for_user(owner_id) as session:
            used = await session.execute(
                select(func.count())
                .select_from(ManualRefreshLog)
                .where(
                    ManualRefreshLog.owner_id == owner_id,
                    ManualRefreshLog.requested_at >= since,
                )
            )
            if int(used.scalar_one()) >= self._manual_refresh_per_day:
                raise RateLimitedError(
                    "you have used today's manual refreshes; the weekly crawl still runs",
                    limit=self._manual_refresh_per_day,
                )
            session.add(ManualRefreshLog(owner_id=owner_id, company_id=company_id))

    async def salary_band(self, owner_id: uuid.UUID, posting_ids: list[uuid.UUID]) -> object:
        async with self._db.shared() as session:
            rows = await session.execute(
                select(
                    JobPosting.salary_min, JobPosting.salary_max, JobPosting.salary_currency
                ).where(
                    JobPosting.id.in_(posting_ids),
                    JobPosting.salary_min.is_not(None),
                    JobPosting.salary_currency.is_not(None),
                )
            )
            return band_from([(r[0], r[1] or r[0], r[2]) for r in rows.all()])


# --- helpers ---------------------------------------------------------------


def _any_of(conditions: list[ColumnElement[bool]]) -> ColumnElement[bool]:
    """A posting is in scope if it matches a watched company *or* a chosen market."""
    return or_(*conditions) if len(conditions) > 1 else conditions[0]


async def _ensure_company(session: AsyncSession, name: str) -> Company:
    normalized = normalize(name)
    existing = await session.execute(select(Company).where(Company.normalized_name == normalized))
    company = existing.scalar_one_or_none()
    if company is None:
        company = Company(name=name.strip(), normalized_name=normalized)
        session.add(company)
        await session.flush()
    return company


async def _upsert_posting(
    session: AsyncSession,
    source_id: uuid.UUID,
    company_id: uuid.UUID,
    posting: NormalizedPosting,
) -> None:
    existing = await session.execute(
        select(JobPosting).where(JobPosting.canonical_key == posting.canonical_key)
    )
    row = existing.scalar_one_or_none()
    now = utcnow()
    if row is None:
        session.add(
            JobPosting(
                canonical_key=posting.canonical_key,
                company_id=company_id,
                crawl_source_id=source_id,
                title=posting.title,
                location=posting.location,
                description=posting.description,
                url=posting.url,
                source_kind=str(posting.source_kind),
                posted_on=posting.posted_on,
                salary_min=posting.salary.min_amount if posting.salary else None,
                salary_max=posting.salary.max_amount if posting.salary else None,
                salary_currency=posting.salary.currency if posting.salary else None,
                status=str(PostingStatus.OPEN),
                first_seen_at=now,
                last_seen_at=now,
            )
        )
        return

    row.last_seen_at = now
    row.status = str(PostingStatus.OPEN)
    # The same opening can arrive from several sources — a company's Greenhouse
    # board and its own career page carrying JSON-LD. Dedup collapses them into
    # one row, and that row belongs to whichever source saw it last, so expiry
    # (which is scoped per source) stays coherent instead of leaving a posting
    # that no crawl is responsible for.
    row.crawl_source_id = source_id
    row.title = posting.title
    row.description = posting.description
    row.url = posting.url
    if posting.salary is not None:
        row.salary_min = posting.salary.min_amount
        row.salary_max = posting.salary.max_amount
        row.salary_currency = posting.salary.currency


async def _expire_unseen(session: AsyncSession, source_id: uuid.UUID, seen_keys: set[str]) -> int:
    """A posting missing from a crawl is marked expired, never deleted."""
    query = (
        update(JobPosting)
        .where(
            JobPosting.crawl_source_id == source_id,
            JobPosting.status == str(PostingStatus.OPEN),
        )
        .values(status=str(PostingStatus.EXPIRED))
    )
    if seen_keys:
        query = query.where(JobPosting.canonical_key.notin_(seen_keys))
    result = await session.execute(query)
    return int(getattr(result, "rowcount", 0) or 0)


def _subscription_view(row: CompanySubscription) -> CompanySubscriptionView:
    return CompanySubscriptionView(
        id=row.id,
        company_id=row.company_id,
        company_name=row.company_name,
        role_title=row.role_title,
        role_id=row.role_id,
        url=row.url,
        coverage=Coverage(row.coverage),
        last_refreshed_at=row.last_refreshed_at,
    )


def _shared_posting_view(posting: JobPosting, company_name: str) -> PostingView:
    salary = (
        SalaryRange(
            min_amount=posting.salary_min,
            max_amount=posting.salary_max or posting.salary_min,
            currency=posting.salary_currency or "",
        )
        if posting.salary_min is not None
        else None
    )
    return PostingView(
        id=posting.id,
        company_name=company_name,
        title=posting.title,
        location=posting.location,
        url=posting.url,
        description=posting.description,
        visibility=Visibility.SHARED,
        salary=salary,
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
