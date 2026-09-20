"""Composition root.

The only place that knows about every module at once. Modules are wired here
and handed their collaborators; none of them reaches for another's internals.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache

from kernel.ai_gateway import AiGateway
from kernel.auth import JwksResolver, TokenVerifier
from kernel.config import Settings, get_settings
from kernel.db import Database
from kernel.storage import ObjectStore
from modules.assessment.public import AssessmentService
from modules.identity.public import IdentityService
from modules.market.public import CrawlIngest, MarketService
from modules.profile.infra.connectors import GitHubConnector, JiraConnector
from modules.profile.public import ProfileService
from modules.rolemap.public import RoleMapService


@dataclass(frozen=True, slots=True)
class Container:
    settings: Settings
    database: Database
    verifier: TokenVerifier
    identity: IdentityService
    profile: ProfileService
    market: MarketService
    rolemap: RoleMapService
    assessment: AssessmentService
    object_store: ObjectStore

    async def aclose(self) -> None:
        await self.database.dispose()


def build(settings: Settings | None = None) -> Container:
    settings = settings or get_settings()
    database = Database(settings)
    object_store = ObjectStore(settings)

    identity = IdentityService(
        database,
        default_monthly_cap_usd=Decimal(str(settings.ai_default_monthly_budget_usd)),
    )

    # identity supplies the gateway's credential and budget ports, which is how
    # the kernel stays free of any domain import.
    gateway = AiGateway(settings=settings, credentials=identity, budget=identity)

    profile = ProfileService(
        database,
        object_store=object_store,
        connectors={
            "github": GitHubConnector(settings.github_api_base_url),
            "jira": JiraConnector(settings.jira_api_base_url),
        },
        resume_max_bytes=settings.resume_max_bytes,
        resume_max_pages=settings.resume_max_pages,
        http_timeout_seconds=settings.crawl_http_timeout_seconds,
        user_agent=settings.service_name,
    )
    market = MarketService(database, manual_refresh_per_day=settings.crawl_manual_refresh_per_day)
    rolemap = RoleMapService(
        database,
        market=market,
        gateway=gateway,
        embedding_model=settings.embedding_model_name,
    )
    assessment = AssessmentService(
        database,
        profile=profile,
        rolemap=rolemap,
        gateway=gateway,
        confidence_threshold=settings.assessment_confidence_threshold,
    )

    verifier = TokenVerifier(
        issuer=settings.clerk_issuer,
        audience=settings.clerk_audience,
        resolver=JwksResolver(settings.clerk_jwks_url, settings.clerk_jwks_cache_seconds),
    )

    return Container(
        settings=settings,
        database=database,
        verifier=verifier,
        identity=identity,
        profile=profile,
        market=market,
        rolemap=rolemap,
        assessment=assessment,
        object_store=object_store,
    )


def build_crawl_ingest(settings: Settings | None = None) -> tuple[Database, CrawlIngest]:
    """The crawler's wiring: the crawler role's connection and nothing else.

    No object store, no gateway, no credential access — this process holds no
    secrets by design.
    """
    settings = settings or get_settings()
    if settings.crawler_database_url is None:
        raise RuntimeError("CRAWLER_DATABASE_URL is required to run the crawler")
    database = Database(settings, url=str(settings.crawler_database_url))
    return database, CrawlIngest(database)


@lru_cache(maxsize=1)
def container() -> Container:
    return build()
