"""The market component.

Companies, job postings and crawl sources: the market the user is measured
against.

This file is the component's public API. Everything else in the package is
private: other components, the delivery mechanisms and the composition root
import only what is listed here (import-linter contract
``market-public-surface``).
"""

from advisor.market import jobs
from advisor.market.crawling.run import (
    crawl_all,
)
from advisor.market.infra.unit_of_work import (
    SqlMarketUnitOfWork,
)
from advisor.market.service import (
    BASELINE_SOURCES,
    BaselineSource,
    CompanySubscriptionView,
    Coverage,
    CrawlIngest,
    CrawlSourceView,
    MarketService,
    NormalizedPosting,
    PostingStatus,
    PostingView,
    SalaryBand,
    SalaryRange,
    SourceKind,
    SourceOrigin,
    Visibility,
    band_from,
    canonical_key,
)

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
    "SqlMarketUnitOfWork",
    "Visibility",
    "band_from",
    "canonical_key",
    "crawl_all",
    "jobs",
]
