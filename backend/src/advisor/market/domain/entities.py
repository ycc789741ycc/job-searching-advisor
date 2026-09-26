"""The market's entities: what use cases load, change and save.

Plain data with the rules that belong to it. Nothing here knows how a row is
stored; ``advisor.market.infra`` maps these to and from the database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

from advisor.market.domain.posting import (
    Coverage,
    NormalizedPosting,
    PostingStatus,
    SalaryRange,
    SourceOrigin,
    normalize,
)


class SourceStatus(StrEnum):
    ACTIVE = "active"
    # No longer crawled. Kept, never deleted, so the postings it found still
    # have a source that can expire them.
    RETIRED = "retired"


# --- shared zone -----------------------------------------------------------


@dataclass(slots=True)
class Company:
    id: uuid.UUID
    name: str
    # The dedup key: two spellings of one employer are one company.
    normalized_name: str

    @classmethod
    def named(cls, name: str) -> Company:
        return cls(id=uuid.uuid4(), name=name.strip(), normalized_name=normalize(name))


@dataclass(slots=True)
class CrawlSource:
    id: uuid.UUID
    kind: str
    endpoint: str
    company_id: uuid.UUID | None
    market: str | None
    origin: SourceOrigin
    status: SourceStatus
    last_fetched_at: datetime | None = None
    last_error: str | None = None

    @classmethod
    def board(
        cls, *, kind: str, endpoint: str, company_id: uuid.UUID | None, origin: SourceOrigin
    ) -> CrawlSource:
        return cls(
            id=uuid.uuid4(),
            kind=kind,
            endpoint=endpoint,
            company_id=company_id,
            market=None,
            origin=origin,
            status=SourceStatus.ACTIVE,
        )

    def record_fetch(self, at: datetime, error: str | None) -> None:
        self.last_fetched_at = at
        self.last_error = error

    def make_baseline(self, company_id: uuid.UUID) -> None:
        """A listed board is a baseline one, whoever asked for it first."""
        self.origin = SourceOrigin.BASELINE
        self.status = SourceStatus.ACTIVE
        self.company_id = self.company_id or company_id

    def retire(self) -> bool:
        """Stop crawling it. Returns whether anything changed."""
        if self.status is SourceStatus.RETIRED:
            return False
        self.status = SourceStatus.RETIRED
        return True


@dataclass(frozen=True, slots=True)
class DueSource:
    """A source to crawl now, with the name of the company it belongs to."""

    source: CrawlSource
    company_name: str | None


@dataclass(slots=True)
class JobPosting:
    """A crawled opening, shared by every user whose scope reaches it."""

    id: uuid.UUID
    canonical_key: str
    company_id: uuid.UUID
    crawl_source_id: uuid.UUID | None
    title: str
    location: str | None
    description: str
    url: str
    source_kind: str
    posted_on: date | None
    salary: SalaryRange | None
    status: PostingStatus
    first_seen_at: datetime
    last_seen_at: datetime

    @classmethod
    def first_seen(
        cls,
        posting: NormalizedPosting,
        *,
        company_id: uuid.UUID,
        source_id: uuid.UUID,
        at: datetime,
    ) -> JobPosting:
        return cls(
            id=uuid.uuid4(),
            canonical_key=posting.canonical_key,
            company_id=company_id,
            crawl_source_id=source_id,
            title=posting.title,
            location=posting.location,
            description=posting.description,
            url=posting.url,
            source_kind=str(posting.source_kind),
            posted_on=posting.posted_on,
            salary=posting.salary,
            status=PostingStatus.OPEN,
            first_seen_at=at,
            last_seen_at=at,
        )

    def seen_again(self, posting: NormalizedPosting, *, source_id: uuid.UUID, at: datetime) -> None:
        self.last_seen_at = at
        self.status = PostingStatus.OPEN
        # The same opening can arrive from several sources — a company's
        # Greenhouse board and its own career page carrying JSON-LD. Dedup
        # collapses them into one posting, and it belongs to whichever source
        # saw it last, so expiry (which is scoped per source) stays coherent
        # instead of leaving a posting that no crawl is responsible for.
        self.crawl_source_id = source_id
        self.title = posting.title
        self.description = posting.description
        self.url = posting.url
        if posting.salary is not None:
            self.salary = posting.salary


@dataclass(frozen=True, slots=True)
class PostingScope:
    """Which shared postings a user's role map is built from (domain decision 15).

    A posting is in scope if it is from a company they watch *or* in a market
    they chose. A user with no market also gets the platform's baseline
    postings, so a first role map has something to group; with markets chosen,
    baseline postings in them are already in scope through the market match.
    """

    company_ids: tuple[uuid.UUID, ...]
    markets: tuple[str, ...]

    @property
    def includes_baseline(self) -> bool:
        return not self.markets


# --- owner zone ------------------------------------------------------------


@dataclass(slots=True)
class CompanySubscription:
    """A RoleSubscription: one role at one company (domain decision 19)."""

    id: uuid.UUID
    owner_id: uuid.UUID
    company_id: uuid.UUID
    company_name: str
    role_title: str
    role_id: uuid.UUID | None
    url: str | None
    # Coverage belongs to the company's board, not to one role there.
    coverage: Coverage
    last_refreshed_at: datetime | None = None

    @classmethod
    def new(
        cls,
        *,
        owner_id: uuid.UUID,
        company: Company,
        role_title: str,
        role_id: uuid.UUID | None,
        url: str | None,
        coverage: Coverage,
    ) -> CompanySubscription:
        return cls(
            id=uuid.uuid4(),
            owner_id=owner_id,
            company_id=company.id,
            company_name=company.name,
            role_title=role_title,
            role_id=role_id,
            url=url,
            coverage=coverage,
        )

    def resubscribe(self, *, role_id: uuid.UUID | None, url: str | None) -> None:
        """Subscribing again to the same role updates it; it never duplicates."""
        self.role_id = role_id or self.role_id
        self.url = url or self.url


@dataclass(slots=True)
class PrivateJobPosting:
    """A JD the user pasted. Private to them, always."""

    id: uuid.UUID
    owner_id: uuid.UUID
    canonical_key: str
    company_name: str
    title: str
    location: str | None
    description: str
    url: str | None
    # A matching crawled posting, so the user gets its weekly updates. Nothing
    # flows back the other way.
    shared_posting_id: uuid.UUID | None
    vector: list[float] | None = field(default=None)


def refresh_allowed(*, used_today: int, per_day: int) -> bool:
    """Manual re-crawls are capped per day; the weekly schedule is the norm."""
    return used_today < per_day
