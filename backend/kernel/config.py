"""The one place the process reads its environment.

Read once at startup into a validated, typed object; nothing else in the code
base touches ``os.environ``. Required settings have no default and fail startup
when missing — that is deliberate for hostnames, URLs, connection strings and
secrets (design-guideline shared-context: Configuration).
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,  # the process environment is the source; .env is loaded by make
        extra="ignore",
        frozen=True,
    )

    # --- Application --------------------------------------------------------
    app_env: str = Field(alias="APP_ENV")
    service_name: str = Field(default="job-searching-advisor", alias="SERVICE_NAME")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    port: int = Field(default=8000, alias="PORT")
    # Browser origins allowed to call the API — the SPA's origin, which is not
    # the same thing as the API's own URL or the OAuth redirect base.
    cors_allowed_origins: str = Field(default="", alias="CORS_ALLOWED_ORIGINS")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    # --- Persistence --------------------------------------------------------
    # Optional at the type level because the crawler must NOT hold app_rw's
    # credentials. Each entrypoint asserts what it actually needs at startup —
    # see require_for(), below.
    database_url: PostgresDsn | None = Field(default=None, alias="DATABASE_URL")
    crawler_database_url: PostgresDsn | None = Field(default=None, alias="CRAWLER_DATABASE_URL")
    db_pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    db_statement_timeout_ms: int = Field(default=30_000, alias="DB_STATEMENT_TIMEOUT_MS")

    # --- Auth (api only) ----------------------------------------------------
    clerk_issuer: str | None = Field(default=None, alias="CLERK_ISSUER")
    clerk_audience: str | None = Field(default=None, alias="CLERK_AUDIENCE")
    clerk_jwks_url: str | None = Field(default=None, alias="CLERK_JWKS_URL")
    clerk_jwks_cache_seconds: int = Field(default=600, alias="CLERK_JWKS_CACHE_SECONDS")

    # --- Encryption ---------------------------------------------------------
    # Absent on the crawler by design; anything needing it fails loudly there.
    master_encryption_key: SecretStr | None = Field(default=None, alias="MASTER_ENCRYPTION_KEY")

    # --- Object storage -----------------------------------------------------
    # Where the services reach object storage — a compose service name in a
    # container network.
    s3_endpoint_url: str | None = Field(default=None, alias="S3_ENDPOINT_URL")
    # Where a browser reaches it. A presigned URL is signed against its host,
    # so signing with the internal name would hand the client an address it
    # cannot resolve.
    s3_public_endpoint_url: str | None = Field(default=None, alias="S3_PUBLIC_ENDPOINT_URL")
    s3_region: str | None = Field(default=None, alias="S3_REGION")
    s3_bucket: str | None = Field(default=None, alias="S3_BUCKET")
    s3_access_key_id: SecretStr | None = Field(default=None, alias="S3_ACCESS_KEY_ID")
    s3_secret_access_key: SecretStr | None = Field(default=None, alias="S3_SECRET_ACCESS_KEY")
    signed_url_ttl_seconds: int = Field(default=300, alias="SIGNED_URL_TTL_SECONDS")

    # --- Connector OAuth (api and worker; never the crawler) ----------------
    oauth_redirect_base_url: str | None = Field(default=None, alias="OAUTH_REDIRECT_BASE_URL")
    github_oauth_client_id: str | None = Field(default=None, alias="GITHUB_OAUTH_CLIENT_ID")
    github_oauth_client_secret: SecretStr | None = Field(
        default=None, alias="GITHUB_OAUTH_CLIENT_SECRET"
    )
    github_api_base_url: str | None = Field(default=None, alias="GITHUB_API_BASE_URL")
    jira_oauth_client_id: str | None = Field(default=None, alias="JIRA_OAUTH_CLIENT_ID")
    jira_oauth_client_secret: SecretStr | None = Field(
        default=None, alias="JIRA_OAUTH_CLIENT_SECRET"
    )
    jira_api_base_url: str | None = Field(default=None, alias="JIRA_API_BASE_URL")
    jira_oauth_base_url: str | None = Field(default=None, alias="JIRA_OAUTH_BASE_URL")

    # --- AI gateway ---------------------------------------------------------
    ai_request_timeout_seconds: int = Field(default=120, alias="AI_REQUEST_TIMEOUT_SECONDS")
    ai_max_output_retries: int = Field(default=2, alias="AI_MAX_OUTPUT_RETRIES")
    ai_default_monthly_budget_usd: float = Field(
        default=20.0, alias="AI_DEFAULT_MONTHLY_BUDGET_USD"
    )

    # --- Uploads / parsing --------------------------------------------------
    resume_max_bytes: int = Field(default=10_485_760, alias="RESUME_MAX_BYTES")
    resume_max_pages: int = Field(default=30, alias="RESUME_MAX_PAGES")
    parse_timeout_seconds: int = Field(default=60, alias="PARSE_TIMEOUT_SECONDS")

    # --- Crawler ------------------------------------------------------------
    crawl_user_agent: str = Field(default="JobSearchingAdvisorBot/1.0", alias="CRAWL_USER_AGENT")
    crawl_http_timeout_seconds: int = Field(default=30, alias="CRAWL_HTTP_TIMEOUT_SECONDS")
    crawl_rate_limit_per_host_per_second: float = Field(
        default=1.0, alias="CRAWL_RATE_LIMIT_PER_HOST_PER_SECOND"
    )
    crawl_manual_refresh_per_day: int = Field(default=3, alias="CRAWL_MANUAL_REFRESH_PER_DAY")
    embedding_model_name: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2", alias="EMBEDDING_MODEL_NAME"
    )

    # --- Assessment ---------------------------------------------------------
    assessment_confidence_threshold: float = Field(
        default=0.6, alias="ASSESSMENT_CONFIDENCE_THRESHOLD"
    )

    @field_validator("log_level")
    @classmethod
    def _known_level(cls, value: str) -> str:
        allowed = {"DEBUG", "INFO", "WARN", "WARNING", "ERROR"}
        upper = value.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(allowed)}")
        return upper

    @field_validator("assessment_confidence_threshold")
    @classmethod
    def _unit_interval(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("ASSESSMENT_CONFIDENCE_THRESHOLD must be between 0 and 1")
        return value

    def require_database_url(self) -> str:
        """The app's connection string. Absent on the crawler by design."""
        if self.database_url is None:
            raise MissingSecretError(
                "DATABASE_URL is not set on this process. The crawler uses "
                "CRAWLER_DATABASE_URL and must not hold app_rw's credentials."
            )
        return str(self.database_url)

    def require_crawler_database_url(self) -> str:
        if self.crawler_database_url is None:
            raise MissingSecretError("CRAWLER_DATABASE_URL is required to run the crawler")
        return str(self.crawler_database_url)

    def require_for(self, unit: Unit) -> None:
        """Assert this process has what it needs, at startup.

        One settings object is read once, but the three deployables need
        different parts of it — and deliberately must not hold each other's
        secrets. Checking per unit keeps "missing configuration fails at
        startup" true without forcing every process to carry every credential
        (docs/technical_boundaries.md section 4).
        """
        missing = [name for name in _REQUIRED_BY_UNIT[unit] if getattr(self, name) is None]
        if missing:
            raise MissingSecretError(
                f"{unit} is missing required configuration: "
                + ", ".join(sorted(_ENV_NAME[name] for name in missing))
            )

    def require_master_key(self) -> SecretStr:
        """Fail loudly where a secret is needed but the unit must not hold one."""
        if self.master_encryption_key is None:
            raise MissingSecretError(
                "MASTER_ENCRYPTION_KEY is not set on this process. It belongs on "
                "`api` and `worker` only — never on `crawler`."
            )
        return self.master_encryption_key


class MissingSecretError(RuntimeError):
    """A secret this code path needs is absent from the process environment."""


class Unit(StrEnum):
    """The three deployables, which need different parts of the configuration."""

    API = "api"
    WORKER = "worker"
    CRAWLER = "crawler"


_SHARED_STORAGE = (
    "database_url",
    "master_encryption_key",
    "s3_endpoint_url",
    "s3_public_endpoint_url",
    "s3_region",
    "s3_bucket",
    "s3_access_key_id",
    "s3_secret_access_key",
)

_CONNECTORS = (
    "oauth_redirect_base_url",
    "github_oauth_client_id",
    "github_oauth_client_secret",
    "github_api_base_url",
    "jira_oauth_client_id",
    "jira_oauth_client_secret",
    "jira_api_base_url",
    "jira_oauth_base_url",
)

_REQUIRED_BY_UNIT: dict[Unit, tuple[str, ...]] = {
    # The api verifies tokens and starts connector OAuth, so it needs Clerk and
    # the connector client credentials.
    Unit.API: (
        *_SHARED_STORAGE,
        *_CONNECTORS,
        "clerk_issuer",
        "clerk_audience",
        "clerk_jwks_url",
    ),
    # The worker runs AI jobs and connector syncs. It never verifies a token.
    Unit.WORKER: (*_SHARED_STORAGE, *_CONNECTORS),
    # The crawler reads public job boards. No user data, no secrets — not the
    # master key, not a connector token, not even app_rw's connection string.
    Unit.CRAWLER: ("crawler_database_url",),
}

_ENV_NAME: dict[str, str] = {name: name.upper() for name in (*_SHARED_STORAGE, *_CONNECTORS)}
_ENV_NAME.update(
    {
        "clerk_issuer": "CLERK_ISSUER",
        "clerk_audience": "CLERK_AUDIENCE",
        "clerk_jwks_url": "CLERK_JWKS_URL",
        "crawler_database_url": "CRAWLER_DATABASE_URL",
    }
)


def must[T](value: T | None, name: str) -> T:
    """Narrow a setting this process already asserted it has.

    Fields that only some deployables need are optional in the schema, and each
    entrypoint checks its own set with ``Settings.require_for``. This is how a
    call site turns that guarantee into a non-optional type — and still fails
    loudly rather than passing ``None`` onward if the wiring is ever wrong.
    """
    if value is None:
        raise MissingSecretError(f"{name} is required on this process but is not set")
    return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide settings object. Built once, on first call."""
    return Settings()
