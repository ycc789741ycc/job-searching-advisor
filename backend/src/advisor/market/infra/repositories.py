"""SQLAlchemy implementations of the market's repositories.

The six methods come from ``kernel.db.repository.SqlAlchemyRepository``. Each
class here names its model, maps rows to entities and back, and turns its
filter's set fields into conditions.
"""

from __future__ import annotations

import uuid
from typing import ClassVar

from sqlalchemy import exists, or_, select, update
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

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
from advisor.market.infra import mappers, models
from kernel.db.repository import SqlAlchemyRepository

# --- shared zone -----------------------------------------------------------


class SqlAlchemyCompanyRepository(SqlAlchemyRepository[Company, models.Company, CompanyFilter]):
    model = models.Company
    id_column = models.Company.id
    created_column = models.Company.created_at
    noun = "company"

    def to_entity(self, row: models.Company) -> Company:
        return mappers.company(row)

    def to_row(self, entity: Company) -> models.Company:
        return mappers.company_row(entity)

    def apply(self, row: models.Company, entity: Company) -> None:
        mappers.apply_company(row, entity)

    def id_of(self, entity: Company) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: CompanyFilter) -> list[ColumnElement[bool]]:
        found: list[ColumnElement[bool]] = []
        if filter.ids is not None:
            found.append(models.Company.id.in_(filter.ids))
        if filter.normalized_name is not None:
            found.append(models.Company.normalized_name == filter.normalized_name)
        return found


class SqlAlchemyCrawlSourceRepository(
    SqlAlchemyRepository[CrawlSource, models.CrawlSource, CrawlSourceFilter]
):
    model = models.CrawlSource
    id_column = models.CrawlSource.id
    created_column = models.CrawlSource.created_at
    noun = "crawl source"

    def to_entity(self, row: models.CrawlSource) -> CrawlSource:
        return mappers.crawl_source(row)

    def to_row(self, entity: CrawlSource) -> models.CrawlSource:
        return mappers.crawl_source_row(entity)

    def apply(self, row: models.CrawlSource, entity: CrawlSource) -> None:
        mappers.apply_crawl_source(row, entity)

    def id_of(self, entity: CrawlSource) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: CrawlSourceFilter) -> list[ColumnElement[bool]]:
        source = models.CrawlSource
        found: list[ColumnElement[bool]] = []
        if filter.status is not None:
            found.append(source.status == str(filter.status))
        if filter.origin is not None:
            found.append(source.origin == str(filter.origin))
        if filter.company_id is not None:
            found.append(source.company_id == filter.company_id)
        if filter.kind is not None:
            found.append(source.kind == filter.kind)
        if filter.endpoint is not None:
            found.append(source.endpoint == filter.endpoint)
        return found


class SqlAlchemyJobPostingRepository(
    SqlAlchemyRepository[JobPosting, models.JobPosting, JobPostingFilter]
):
    model = models.JobPosting
    id_column = models.JobPosting.id
    created_column = models.JobPosting.created_at
    noun = "job posting"

    def to_entity(self, row: models.JobPosting) -> JobPosting:
        return mappers.job_posting(row)

    def to_row(self, entity: JobPosting) -> models.JobPosting:
        return mappers.job_posting_row(entity)

    def apply(self, row: models.JobPosting, entity: JobPosting) -> None:
        mappers.apply_job_posting(row, entity)

    def id_of(self, entity: JobPosting) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: JobPostingFilter) -> list[ColumnElement[bool]]:
        posting = models.JobPosting
        found: list[ColumnElement[bool]] = []
        if filter.ids is not None:
            found.append(posting.id.in_(filter.ids))
        if filter.canonical_key is not None:
            found.append(posting.canonical_key == filter.canonical_key)
        if filter.status is not None:
            found.append(posting.status == str(filter.status))
        if filter.has_salary is True:
            found += [posting.salary_min.is_not(None), posting.salary_currency.is_not(None)]
        elif filter.has_salary is False:
            found.append(posting.salary_min.is_(None))
        if filter.missing_embedding_for is not None:
            embedding = models.PostingEmbedding
            found.append(
                ~exists().where(
                    embedding.job_posting_id == posting.id,
                    embedding.model_name == filter.missing_embedding_for,
                )
            )
        return found

    async def expire_unseen(self, source_id: uuid.UUID, seen_keys: set[str]) -> int:
        posting = models.JobPosting
        query = (
            update(posting)
            .where(posting.crawl_source_id == source_id, posting.status == str(PostingStatus.OPEN))
            .values(status=str(PostingStatus.EXPIRED))
        )
        if seen_keys:
            query = query.where(posting.canonical_key.notin_(seen_keys))
        result = await self._session.execute(query)
        return int(getattr(result, "rowcount", 0) or 0)

    async def get_open_in_scope(self, scope: PostingScope) -> list[JobPosting]:
        posting = models.JobPosting
        either: list[ColumnElement[bool]] = []
        if scope.company_ids:
            either.append(posting.company_id.in_(scope.company_ids))
        if scope.markets:
            either.append(posting.location.in_(scope.markets))
        if scope.includes_baseline:
            either.append(
                posting.crawl_source_id.in_(
                    select(models.CrawlSource.id).where(
                        models.CrawlSource.origin == str(SourceOrigin.BASELINE)
                    )
                )
            )
        rows = await self._session.execute(
            select(posting)
            .where(posting.status == str(PostingStatus.OPEN), or_(*either))
            .order_by(posting.created_at.desc(), posting.id.desc())
        )
        return [mappers.job_posting(row) for row in rows.scalars()]


class SqlAlchemyPostingEmbeddingRepository(
    SqlAlchemyRepository[PostingEmbedding, models.PostingEmbedding, PostingEmbeddingFilter]
):
    model = models.PostingEmbedding
    id_column = models.PostingEmbedding.job_posting_id
    created_column = models.PostingEmbedding.computed_at
    noun = "posting embedding"

    def to_entity(self, row: models.PostingEmbedding) -> PostingEmbedding:
        return mappers.posting_embedding(row)

    def to_row(self, entity: PostingEmbedding) -> models.PostingEmbedding:
        return mappers.posting_embedding_row(entity)

    def apply(self, row: models.PostingEmbedding, entity: PostingEmbedding) -> None:
        mappers.apply_posting_embedding(row, entity)

    def id_of(self, entity: PostingEmbedding) -> uuid.UUID:
        return entity.posting_id

    def conditions(self, filter: PostingEmbeddingFilter) -> list[ColumnElement[bool]]:
        embedding = models.PostingEmbedding
        found: list[ColumnElement[bool]] = []
        if filter.posting_ids is not None:
            found.append(embedding.job_posting_id.in_(filter.posting_ids))
        if filter.model_name is not None:
            found.append(embedding.model_name == filter.model_name)
        return found


# --- owner zone ------------------------------------------------------------


class SqlAlchemySubscriptionRepository(
    SqlAlchemyRepository[CompanySubscription, models.CompanySubscription, SubscriptionFilter]
):
    model = models.CompanySubscription
    id_column = models.CompanySubscription.id
    created_column = models.CompanySubscription.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = (
        models.CompanySubscription.owner_id
    )
    noun = "subscription"

    def to_entity(self, row: models.CompanySubscription) -> CompanySubscription:
        return mappers.subscription(row)

    def to_row(self, entity: CompanySubscription) -> models.CompanySubscription:
        return mappers.subscription_row(entity)

    def apply(self, row: models.CompanySubscription, entity: CompanySubscription) -> None:
        mappers.apply_subscription(row, entity)

    def id_of(self, entity: CompanySubscription) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: SubscriptionFilter) -> list[ColumnElement[bool]]:
        subscription = models.CompanySubscription
        found: list[ColumnElement[bool]] = []
        if filter.company_id is not None:
            found.append(subscription.company_id == filter.company_id)
        if filter.role_title is not None:
            found.append(subscription.role_title == filter.role_title)
        return found


class SqlAlchemyMarketPreferenceRepository(
    SqlAlchemyRepository[MarketPreference, models.MarketPreference, MarketPreferenceFilter]
):
    model = models.MarketPreference
    id_column = models.MarketPreference.id
    created_column = models.MarketPreference.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = (
        models.MarketPreference.owner_id
    )
    noun = "market preference"

    def to_entity(self, row: models.MarketPreference) -> MarketPreference:
        return mappers.market_preference(row)

    def to_row(self, entity: MarketPreference) -> models.MarketPreference:
        return mappers.market_preference_row(entity)

    def apply(self, row: models.MarketPreference, entity: MarketPreference) -> None:
        mappers.apply_market_preference(row, entity)

    def id_of(self, entity: MarketPreference) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: MarketPreferenceFilter) -> list[ColumnElement[bool]]:
        if filter.market is None:
            return []
        return [models.MarketPreference.market == filter.market]


class SqlAlchemyPrivateJobPostingRepository(
    SqlAlchemyRepository[PrivateJobPosting, models.PrivateJobPosting, PrivateJobPostingFilter]
):
    model = models.PrivateJobPosting
    id_column = models.PrivateJobPosting.id
    created_column = models.PrivateJobPosting.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = (
        models.PrivateJobPosting.owner_id
    )
    noun = "job description"

    def to_entity(self, row: models.PrivateJobPosting) -> PrivateJobPosting:
        return mappers.private_posting(row)

    def to_row(self, entity: PrivateJobPosting) -> models.PrivateJobPosting:
        return mappers.private_posting_row(entity)

    def apply(self, row: models.PrivateJobPosting, entity: PrivateJobPosting) -> None:
        mappers.apply_private_posting(row, entity)

    def id_of(self, entity: PrivateJobPosting) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: PrivateJobPostingFilter) -> list[ColumnElement[bool]]:
        vector = models.PrivateJobPosting.vector
        if filter.has_vector is True:
            return [vector.is_not(None)]
        if filter.has_vector is False:
            return [vector.is_(None)]
        return []


class SqlAlchemyManualRefreshRepository(
    SqlAlchemyRepository[ManualRefresh, models.ManualRefreshLog, ManualRefreshFilter]
):
    model = models.ManualRefreshLog
    id_column = models.ManualRefreshLog.id
    created_column = models.ManualRefreshLog.requested_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = (
        models.ManualRefreshLog.owner_id
    )
    noun = "manual refresh"

    def to_entity(self, row: models.ManualRefreshLog) -> ManualRefresh:
        return mappers.manual_refresh(row)

    def to_row(self, entity: ManualRefresh) -> models.ManualRefreshLog:
        return mappers.manual_refresh_row(entity)

    def apply(self, row: models.ManualRefreshLog, entity: ManualRefresh) -> None:
        mappers.apply_manual_refresh(row, entity)

    def id_of(self, entity: ManualRefresh) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: ManualRefreshFilter) -> list[ColumnElement[bool]]:
        if filter.requested_since is None:
            return []
        return [models.ManualRefreshLog.requested_at >= filter.requested_since]
