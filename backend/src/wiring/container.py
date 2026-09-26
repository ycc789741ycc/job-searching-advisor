"""Composition root.

The only place that knows about every module at once. Modules are wired here
and handed their collaborators; none of them reaches for another's internals.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache

from advisor.assessment import AssessmentService
from advisor.gapplan import GapPlanService
from advisor.identity import (
    AuthService,
    GoogleEndpoints,
    GoogleOidc,
    GoogleSignIn,
    IdentityService,
)
from advisor.market import CrawlIngest, MarketService, create_market_service
from advisor.profile import (
    GitHubConnector,
    JiraConnector,
    ProfileService,
    create_profile_service,
)
from advisor.resume import ResumeService
from advisor.rolemap import RoleMapService
from advisor.target import TargetService
from kernel.ai_gateway import AiGateway
from kernel.auth import ALGORITHM, JwksResolver, StaticSecretResolver, TokenVerifier
from kernel.config import Settings, get_settings, must
from kernel.db import Database
from kernel.storage import ObjectStore
from wiring.crawl import build_crawl_ingest

# Google rotates its signing keys over days; an hour keeps the fetch rare while
# a newly published key is still picked up well before it is used.
_GOOGLE_KEYS_CACHE_SECONDS = 3600


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
    _google: GoogleSignIn | None = None

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

    @property
    def google_sign_in(self) -> GoogleSignIn | None:
        """Google sign-in, or None when it is not configured.

        Built on first use, like the verifier: only `api` signs anyone in.
        """
        settings = self.settings
        if not settings.google_sign_in_enabled:
            return None
        if self._google is None:
            api_base = must(settings.auth_public_api_base_url, "AUTH_PUBLIC_API_BASE_URL")
            endpoints = GoogleEndpoints(
                authorize_url=must(
                    settings.google_oauth_authorize_url, "GOOGLE_OAUTH_AUTHORIZE_URL"
                ),
                token_url=must(settings.google_oauth_token_url, "GOOGLE_OAUTH_TOKEN_URL"),
                client_id=must(settings.google_oauth_client_id, "GOOGLE_OAUTH_CLIENT_ID"),
                client_secret=must(
                    settings.google_oauth_client_secret, "GOOGLE_OAUTH_CLIENT_SECRET"
                ).get_secret_value(),
                redirect_uri=f"{api_base.rstrip('/')}/api/v1/auth/google/callback",
            )
            provider = GoogleOidc(
                endpoints,
                keys=JwksResolver(
                    must(settings.google_oauth_jwks_url, "GOOGLE_OAUTH_JWKS_URL"),
                    cache_seconds=_GOOGLE_KEYS_CACHE_SECONDS,
                ),
                timeout_seconds=settings.crawl_http_timeout_seconds,
                user_agent=settings.service_name,
            )
            self._google = GoogleSignIn(self.auth, provider, secret=settings.require_auth_secret())
        return self._google

    def open_crawl_ingest(self) -> tuple[Database, CrawlIngest]:
        """A crawler-role connection, for a worker job that writes postings.

        The caller disposes of the returned database when it is done.
        """
        return build_crawl_ingest(self.settings)

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

    profile = create_profile_service(
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
    market = create_market_service(
        database, manual_refresh_per_day=settings.crawl_manual_refresh_per_day
    )
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


@lru_cache(maxsize=1)
def container() -> Container:
    return build()
