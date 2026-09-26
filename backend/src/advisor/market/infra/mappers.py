"""ORM rows to market entities and back. No rules live here, only shape."""

from __future__ import annotations

from advisor.market.domain import (
    Company,
    CompanySubscription,
    Coverage,
    CrawlSource,
    JobPosting,
    PostingStatus,
    PrivateJobPosting,
    SalaryRange,
    SourceOrigin,
    SourceStatus,
)
from advisor.market.infra import models

# --- company ---------------------------------------------------------------


def company(row: models.Company) -> Company:
    return Company(id=row.id, name=row.name, normalized_name=row.normalized_name)


def company_row(entity: Company) -> models.Company:
    return models.Company(id=entity.id, name=entity.name, normalized_name=entity.normalized_name)


# --- crawl source ----------------------------------------------------------


def crawl_source(row: models.CrawlSource) -> CrawlSource:
    return CrawlSource(
        id=row.id,
        kind=row.kind,
        endpoint=row.endpoint,
        company_id=row.company_id,
        market=row.market,
        origin=SourceOrigin(row.origin),
        status=SourceStatus(row.status),
        last_fetched_at=row.last_fetched_at,
        last_error=row.last_error,
    )


def crawl_source_row(entity: CrawlSource) -> models.CrawlSource:
    row = models.CrawlSource(id=entity.id)
    apply_crawl_source(row, entity)
    return row


def apply_crawl_source(row: models.CrawlSource, entity: CrawlSource) -> None:
    row.kind = entity.kind
    row.endpoint = entity.endpoint
    row.company_id = entity.company_id
    row.market = entity.market
    row.origin = str(entity.origin)
    row.status = str(entity.status)
    row.last_fetched_at = entity.last_fetched_at
    row.last_error = entity.last_error


# --- job posting -----------------------------------------------------------


def salary(row: models.JobPosting) -> SalaryRange | None:
    if row.salary_min is None:
        return None
    return SalaryRange(
        min_amount=row.salary_min,
        max_amount=row.salary_max or row.salary_min,
        currency=row.salary_currency or "",
    )


def job_posting(row: models.JobPosting) -> JobPosting:
    return JobPosting(
        id=row.id,
        canonical_key=row.canonical_key,
        company_id=row.company_id,
        crawl_source_id=row.crawl_source_id,
        title=row.title,
        location=row.location,
        description=row.description,
        url=row.url,
        source_kind=row.source_kind,
        posted_on=row.posted_on,
        salary=salary(row),
        status=PostingStatus(row.status),
        first_seen_at=row.first_seen_at,
        last_seen_at=row.last_seen_at,
    )


def job_posting_row(entity: JobPosting) -> models.JobPosting:
    row = models.JobPosting(id=entity.id, first_seen_at=entity.first_seen_at)
    apply_job_posting(row, entity)
    return row


def apply_job_posting(row: models.JobPosting, entity: JobPosting) -> None:
    row.canonical_key = entity.canonical_key
    row.company_id = entity.company_id
    row.crawl_source_id = entity.crawl_source_id
    row.title = entity.title
    row.location = entity.location
    row.description = entity.description
    row.url = entity.url
    row.source_kind = entity.source_kind
    row.posted_on = entity.posted_on
    row.status = str(entity.status)
    row.last_seen_at = entity.last_seen_at
    if entity.salary is not None:
        row.salary_min = entity.salary.min_amount
        row.salary_max = entity.salary.max_amount
        row.salary_currency = entity.salary.currency


# --- owner zone ------------------------------------------------------------


def subscription(row: models.CompanySubscription) -> CompanySubscription:
    return CompanySubscription(
        id=row.id,
        owner_id=row.owner_id,
        company_id=row.company_id,
        company_name=row.company_name,
        role_title=row.role_title,
        role_id=row.role_id,
        url=row.url,
        coverage=Coverage(row.coverage),
        last_refreshed_at=row.last_refreshed_at,
    )


def subscription_row(entity: CompanySubscription) -> models.CompanySubscription:
    row = models.CompanySubscription(id=entity.id, owner_id=entity.owner_id)
    apply_subscription(row, entity)
    return row


def apply_subscription(row: models.CompanySubscription, entity: CompanySubscription) -> None:
    row.company_id = entity.company_id
    row.company_name = entity.company_name
    row.role_title = entity.role_title
    row.role_id = entity.role_id
    row.url = entity.url
    row.coverage = str(entity.coverage)
    row.last_refreshed_at = entity.last_refreshed_at


def private_posting(row: models.PrivateJobPosting) -> PrivateJobPosting:
    return PrivateJobPosting(
        id=row.id,
        owner_id=row.owner_id,
        canonical_key=row.canonical_key,
        company_name=row.company_name,
        title=row.title,
        location=row.location,
        description=row.description,
        url=row.url,
        shared_posting_id=row.shared_posting_id,
        vector=list(row.vector) if row.vector is not None else None,
    )


def private_posting_row(entity: PrivateJobPosting) -> models.PrivateJobPosting:
    return models.PrivateJobPosting(
        id=entity.id,
        owner_id=entity.owner_id,
        canonical_key=entity.canonical_key,
        company_name=entity.company_name,
        title=entity.title,
        location=entity.location,
        description=entity.description,
        url=entity.url,
        shared_posting_id=entity.shared_posting_id,
        vector=entity.vector,
    )
