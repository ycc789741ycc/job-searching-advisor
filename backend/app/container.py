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
from kernel.config import Settings, Unit, get_settings, must
from kernel.db import Database
from kernel.storage import ObjectStore
from modules.assessment.public import AssessmentService
from modules.identity.public import IdentityService
from modules.market.public import CrawlIngest, MarketService
from modules.profile.infra.connectors import GitHubConnector, JiraConnector
from modules.profile.public import ProfileService
from modules.rolemap.public import RoleMapService


@dataclass
class Container:
    settings: Settings
    database: Database
    identity: IdentityService
    profile: ProfileService
    market: MarketService
    rolemap: RoleMapService
    assessment: AssessmentService
    object_store: ObjectStore
    _verifier: TokenVerifier | None = None

    @property
    def verifier(self) -> TokenVerifier:
        """Built on first use.

        Only `api` verifies tokens, so the worker runs with no Clerk
        configuration at all and must not fail for wanting it.
        """
        if self._verifier is None:
            settings = self.settings
            settings.require_for(Unit.API)
            self._verifier = TokenVerifier(
                issuer=str(settings.clerk_issuer),
                audience=str(settings.clerk_audience),
                resolver=JwksResolver(
                    str(settings.clerk_jwks_url), settings.clerk_jwks_cache_seconds
                ),
            )
        return self._verifier

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
            "github": GitHubConnector(must(settings.github_api_base_url, "GITHUB_API_BASE_URL")),
            "jira": JiraConnector(must(settings.jira_api_base_url, "JIRA_API_BASE_URL")),
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

    return Container(
        settings=settings,
        database=database,
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
    settings.require_for(Unit.CRAWLER)
    database = Database(settings, url=settings.require_crawler_database_url())
    return database, CrawlIngest(database)


@lru_cache(maxsize=1)
def container() -> Container:
    return build()
