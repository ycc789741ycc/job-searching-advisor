"""SQL implementations of the market's repository interfaces.

Every query here is the one the use cases ran before repositories existed, moved
unchanged. Owner-zone repositories still filter on ``owner_id`` although RLS
already does: the database policy is the guard, the filter keeps plans honest.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from advisor.market.domain import (
    Company,
    CompanySubscription,
    Coverage,
    CrawlSource,
    DueSource,
    JobPosting,
    PostingScope,
    PostingStatus,
    PrivateJobPosting,
    SalaryRange,
    SourceOrigin,
)
from advisor.market.infra import mappers, models
from kernel.errors import NotFoundError

# --- shared zone -----------------------------------------------------------


class SqlCompanyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, company_id: uuid.UUID) -> Company | None:
        row = await self._session.get(models.Company, company_id)
        return mappers.company(row) if row is not None else None

    async def by_normalized_name(self, normalized_name: str) -> Company | None:
        result = await self._session.execute(
            select(models.Company).where(models.Company.normalized_name == normalized_name)
        )
        row = result.scalar_one_or_none()
        return mappers.company(row) if row is not None else None

    async def add(self, company: Company) -> None:
        self._session.add(mappers.company_row(company))
        await self._session.flush()


class SqlCrawlSourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, source_id: uuid.UUID) -> CrawlSource | None:
        row = await self._session.get(models.CrawlSource, source_id)
        return mappers.crawl_source(row) if row is not None else None

    async def due(self) -> list[DueSource]:
        rows = await self._session.execute(
            select(models.CrawlSource, models.Company.name)
            .outerjoin(models.Company, models.CrawlSource.company_id == models.Company.id)
            .where(models.CrawlSource.status == "active")
        )
        return [
            DueSource(source=mappers.crawl_source(source), company_name=company_name)
            for source, company_name in rows.all()
        ]

    async def by_endpoint(self, endpoint: str) -> CrawlSource | None:
        result = await self._session.execute(
            select(models.CrawlSource).where(models.CrawlSource.endpoint == endpoint)
        )
        row = result.scalar_one_or_none()
        return mappers.crawl_source(row) if row is not None else None

    async def by_kind_and_endpoint(self, kind: str, endpoint: str) -> CrawlSource | None:
        result = await self._session.execute(
            select(models.CrawlSource).where(
                models.CrawlSource.kind == kind, models.CrawlSource.endpoint == endpoint
            )
        )
        row = result.scalar_one_or_none()
        return mappers.crawl_source(row) if row is not None else None

    async def exists_for_company(self, company_id: uuid.UUID) -> bool:
        result = await self._session.execute(
            select(models.CrawlSource).where(models.CrawlSource.company_id == company_id)
        )
        return result.scalar_one_or_none() is not None

    async def baseline(self) -> list[CrawlSource]:
        rows = await self._session.execute(
            select(models.CrawlSource).where(
                models.CrawlSource.origin == str(SourceOrigin.BASELINE)
            )
        )
        return [mappers.crawl_source(row) for row in rows.scalars()]

    async def add(self, source: CrawlSource) -> None:
        self._session.add(mappers.crawl_source_row(source))
        await self._session.flush()

    async def save(self, source: CrawlSource) -> None:
        row = await self._session.get(models.CrawlSource, source.id)
        if row is None:
            raise NotFoundError("crawl source is not stored", id=str(source.id))
        mappers.apply_crawl_source(row, source)


class SqlJobPostingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def by_canonical_key(self, key: str) -> JobPosting | None:
        result = await self._session.execute(
            select(models.JobPosting).where(models.JobPosting.canonical_key == key)
        )
        row = result.scalar_one_or_none()
        return mappers.job_posting(row) if row is not None else None

    async def add(self, posting: JobPosting) -> None:
        self._session.add(mappers.job_posting_row(posting))
        await self._session.flush()

    async def save(self, posting: JobPosting) -> None:
        row = await self._session.get(models.JobPosting, posting.id)
        if row is None:
            raise NotFoundError("job posting is not stored", id=str(posting.id))
        mappers.apply_job_posting(row, posting)

    async def expire_unseen(self, source_id: uuid.UUID, seen_keys: set[str]) -> int:
        query = (
            update(models.JobPosting)
            .where(
                models.JobPosting.crawl_source_id == source_id,
                models.JobPosting.status == str(PostingStatus.OPEN),
            )
            .values(status=str(PostingStatus.EXPIRED))
        )
        if seen_keys:
            query = query.where(models.JobPosting.canonical_key.notin_(seen_keys))
        result = await self._session.execute(query)
        return int(getattr(result, "rowcount", 0) or 0)

    async def open_in_scope(self, scope: PostingScope) -> list[tuple[JobPosting, str]]:
        posting = models.JobPosting
        query = (
            select(posting, models.Company.name)
            .join(models.Company, posting.company_id == models.Company.id)
            .where(posting.status == str(PostingStatus.OPEN))
        )
        conditions: list[ColumnElement[bool]] = []
        if scope.company_ids:
            conditions.append(posting.company_id.in_(scope.company_ids))
        if scope.markets:
            conditions.append(posting.location.in_(scope.markets))
        if scope.includes_baseline:
            conditions.append(
                posting.crawl_source_id.in_(
                    select(models.CrawlSource.id).where(
                        models.CrawlSource.origin == str(SourceOrigin.BASELINE)
                    )
                )
            )
        query = query.where(or_(*conditions) if len(conditions) > 1 else conditions[0])
        rows = await self._session.execute(query)
        return [(mappers.job_posting(row), company_name) for row, company_name in rows.all()]

    async def salary_ranges(self, posting_ids: list[uuid.UUID]) -> list[SalaryRange]:
        posting = models.JobPosting
        rows = await self._session.execute(
            select(posting.salary_min, posting.salary_max, posting.salary_currency).where(
                posting.id.in_(posting_ids),
                posting.salary_min.is_not(None),
                posting.salary_currency.is_not(None),
            )
        )
        return [
            SalaryRange(min_amount=low, max_amount=high or low, currency=currency)
            for low, high, currency in rows.all()
        ]

    async def needing_embeddings(self, model_name: str, limit: int) -> list[JobPosting]:
        embedding = models.PostingEmbedding
        rows = await self._session.execute(
            select(models.JobPosting)
            .outerjoin(
                embedding,
                (embedding.job_posting_id == models.JobPosting.id)
                & (embedding.model_name == model_name),
            )
            .where(embedding.job_posting_id.is_(None))
            .limit(limit)
        )
        return [mappers.job_posting(row) for row in rows.scalars()]

    async def embeddings(
        self, posting_ids: list[uuid.UUID], model_name: str
    ) -> dict[uuid.UUID, list[float]]:
        embedding = models.PostingEmbedding
        rows = await self._session.execute(
            select(embedding.job_posting_id, embedding.vector).where(
                embedding.job_posting_id.in_(posting_ids),
                embedding.model_name == model_name,
            )
        )
        return {row[0]: list(row[1]) for row in rows.all()}

    async def add_embeddings(self, model_name: str, vectors: dict[uuid.UUID, list[float]]) -> None:
        for posting_id, vector in vectors.items():
            self._session.add(
                models.PostingEmbedding(
                    job_posting_id=posting_id, model_name=model_name, vector=vector
                )
            )


# --- fan-out ---------------------------------------------------------------


class SqlWatchers:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def of_company(self, company_id: uuid.UUID) -> set[uuid.UUID]:
        rows = await self._session.execute(
            select(models.CompanySubscription.owner_id)
            .where(models.CompanySubscription.company_id == company_id)
            .distinct()
        )
        return set(rows.scalars())

    async def of_market(self, market: str) -> set[uuid.UUID]:
        rows = await self._session.execute(
            select(models.MarketPreference.owner_id)
            .where(models.MarketPreference.market == market)
            .distinct()
        )
        return set(rows.scalars())

    async def watched_boards(self) -> list[tuple[uuid.UUID, str, str | None]]:
        subscription = models.CompanySubscription
        rows = await self._session.execute(
            select(subscription.company_id, subscription.company_name, subscription.url).distinct()
        )
        return [(company_id, name, url) for company_id, name, url in rows.all()]


# --- owner zone ------------------------------------------------------------


class SqlSubscriptionRepository:
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        self._session = session
        self._owner_id = owner_id

    async def all(self) -> list[CompanySubscription]:
        rows = await self._session.execute(
            select(models.CompanySubscription).where(
                models.CompanySubscription.owner_id == self._owner_id
            )
        )
        return [mappers.subscription(row) for row in rows.scalars()]

    async def get(self, subscription_id: uuid.UUID) -> CompanySubscription | None:
        row = await self._own(subscription_id)
        return mappers.subscription(row) if row is not None else None

    async def find(self, company_id: uuid.UUID, role_title: str) -> CompanySubscription | None:
        result = await self._session.execute(
            select(models.CompanySubscription).where(
                models.CompanySubscription.owner_id == self._owner_id,
                models.CompanySubscription.company_id == company_id,
                models.CompanySubscription.role_title == role_title,
            )
        )
        row = result.scalar_one_or_none()
        return mappers.subscription(row) if row is not None else None

    async def at_company(self, company_id: uuid.UUID) -> list[CompanySubscription]:
        rows = await self._session.execute(
            select(models.CompanySubscription).where(
                models.CompanySubscription.owner_id == self._owner_id,
                models.CompanySubscription.company_id == company_id,
            )
        )
        return [mappers.subscription(row) for row in rows.scalars()]

    async def add(self, subscription: CompanySubscription) -> None:
        self._session.add(mappers.subscription_row(subscription))
        await self._session.flush()

    async def save(self, subscription: CompanySubscription) -> None:
        row = await self._own(subscription.id)
        if row is None:
            raise NotFoundError("subscription is not stored", id=str(subscription.id))
        mappers.apply_subscription(row, subscription)
        await self._session.flush()

    async def remove(self, subscription_id: uuid.UUID) -> None:
        row = await self._own(subscription_id)
        if row is not None:
            await self._session.delete(row)

    async def set_coverage(self, company_id: uuid.UUID, coverage: Coverage) -> None:
        await self._session.execute(
            update(models.CompanySubscription)
            .where(
                models.CompanySubscription.owner_id == self._owner_id,
                models.CompanySubscription.company_id == company_id,
            )
            .values(coverage=str(coverage))
        )

    async def _own(self, subscription_id: uuid.UUID) -> models.CompanySubscription | None:
        row = await self._session.get(models.CompanySubscription, subscription_id)
        return row if row is not None and row.owner_id == self._owner_id else None


class SqlMarketPreferenceRepository:
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        self._session = session
        self._owner_id = owner_id

    async def all(self) -> list[str]:
        rows = await self._session.execute(
            select(models.MarketPreference.market).where(
                models.MarketPreference.owner_id == self._owner_id
            )
        )
        return sorted(rows.scalars())

    async def has(self, market: str) -> bool:
        return await self._row(market) is not None

    async def add(self, market: str) -> None:
        self._session.add(models.MarketPreference(owner_id=self._owner_id, market=market))

    async def remove(self, market: str) -> None:
        row = await self._row(market)
        if row is not None:
            await self._session.delete(row)

    async def _row(self, market: str) -> models.MarketPreference | None:
        result = await self._session.execute(
            select(models.MarketPreference).where(
                models.MarketPreference.owner_id == self._owner_id,
                models.MarketPreference.market == market,
            )
        )
        return result.scalar_one_or_none()


class SqlPrivatePostingRepository:
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        self._session = session
        self._owner_id = owner_id

    async def all(self) -> list[PrivateJobPosting]:
        rows = await self._session.execute(
            select(models.PrivateJobPosting).where(
                models.PrivateJobPosting.owner_id == self._owner_id
            )
        )
        return [mappers.private_posting(row) for row in rows.scalars()]

    async def get(self, posting_id: uuid.UUID) -> PrivateJobPosting | None:
        row = await self._own(posting_id)
        return mappers.private_posting(row) if row is not None else None

    async def add(self, posting: PrivateJobPosting) -> None:
        self._session.add(mappers.private_posting_row(posting))
        await self._session.flush()

    async def vectors(self) -> dict[uuid.UUID, list[float]]:
        rows = await self._session.execute(
            select(models.PrivateJobPosting.id, models.PrivateJobPosting.vector).where(
                models.PrivateJobPosting.owner_id == self._owner_id,
                models.PrivateJobPosting.vector.is_not(None),
            )
        )
        return {posting_id: list(vector) for posting_id, vector in rows.all()}

    async def set_vector(self, posting_id: uuid.UUID, vector: list[float]) -> None:
        row = await self._own(posting_id)
        if row is not None:
            row.vector = vector

    async def _own(self, posting_id: uuid.UUID) -> models.PrivateJobPosting | None:
        row = await self._session.get(models.PrivateJobPosting, posting_id)
        return row if row is not None and row.owner_id == self._owner_id else None


class SqlManualRefreshRepository:
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        self._session = session
        self._owner_id = owner_id

    async def count_since(self, since: datetime) -> int:
        used = await self._session.execute(
            select(func.count())
            .select_from(models.ManualRefreshLog)
            .where(
                models.ManualRefreshLog.owner_id == self._owner_id,
                models.ManualRefreshLog.requested_at >= since,
            )
        )
        return int(used.scalar_one())

    async def record(self, company_id: uuid.UUID) -> None:
        self._session.add(models.ManualRefreshLog(owner_id=self._owner_id, company_id=company_id))
