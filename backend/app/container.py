"""Composition root.

The only place that knows about every module at once. Modules are wired here
and handed their collaborators; none of them reaches for another's internals.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache

from kernel.ai_gateway import AiGateway
from kernel.auth import ALGORITHM, StaticSecretResolver, TokenVerifier
from kernel.config import Settings, Unit, get_settings, must
from kernel.db import Database
from kernel.storage import ObjectStore
from modules.assessment.public import AssessmentService
from modules.gapplan.public import GapPlanService
from modules.identity.public import AuthService, IdentityService
from modules.market.public import CrawlIngest, MarketService
from modules.profile.infra.connectors import GitHubConnector, JiraConnector
from modules.profile.public import ProfileService
from modules.resume.public import ResumeService
from modules.rolemap.public import RoleMapService
from modules.target.public import TargetService


@dataclass
class Container:
    settings: Settings
    database: Database
    identity: IdentityService
    auth: AuthService
    profile: ProfileService
    market: MarketService
    rolemap: RoleMapService
    assessment: AssessmentService
    target: TargetService
    gapplan: GapPlanService
    resume: ResumeService
    object_store: ObjectStore
    _verifier: TokenVerifier | None = None

    @property
    def verifier(self) -> TokenVerifier:
        """Built on first use.

        Only `api` verifies tokens, so the worker runs with no signing secret
        at all and must not fail for wanting one.
        """
        if self._verifier is None:
            settings = self.settings
            self._verifier = TokenVerifier(
                issuer=settings.auth_token_issuer,
                audience=settings.auth_token_audience,
                resolver=StaticSecretResolver(settings.require_auth_secret()),
                algorithms=(ALGORITHM,),
            )
        return self._verifier

    async def aclose(self) -> None:
        await self.database.dispose()


def build(settings: Settings | None = None) -> Container:
    settings = settings or get_settings()
    database = Database(settings)
    object_store = ObjectStore(settings)

    default_cap = Decimal(str(settings.ai_default_monthly_budget_usd))
    identity = IdentityService(database, default_monthly_cap_usd=default_cap)

    # Only the api signs tokens; the worker never does, so the secret is
    # resolved lazily rather than at wiring time.
    auth = AuthService(
        database,
        secret=settings.auth_jwt_secret.get_secret_value() if settings.auth_jwt_secret else "",
        issuer=settings.auth_token_issuer,
        audience=settings.auth_token_audience,
        access_ttl_seconds=settings.auth_access_token_ttl_seconds,
        refresh_ttl_days=settings.auth_refresh_token_ttl_days,
        default_monthly_cap_usd=default_cap,
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
        profile=profile,
        gateway=gateway,
        embedding_model=settings.embedding_model_name,
    )
    assessment = AssessmentService(
        database,
        profile=profile,
        rolemap=rolemap,
        market=market,
        gateway=gateway,
        confidence_threshold=settings.assessment_confidence_threshold,
    )
    target = TargetService(assessment=assessment, market=market, rolemap=rolemap)
    gapplan = GapPlanService(
        database,
        target=target,
        profile=profile,
        assessment=assessment,
        rolemap=rolemap,
        gateway=gateway,
    )
    resume = ResumeService(
        database,
        target=target,
        profile=profile,
        assessment=assessment,
        gateway=gateway,
        object_store=object_store,
    )

    return Container(
        settings=settings,
        database=database,
        identity=identity,
        auth=auth,
        profile=profile,
        market=market,
        rolemap=rolemap,
        assessment=assessment,
        target=target,
        gapplan=gapplan,
        resume=resume,
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
