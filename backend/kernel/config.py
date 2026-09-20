"""The one place the process reads its environment.

Read once at startup into a validated, typed object; nothing else in the code
base touches ``os.environ``. Required settings have no default and fail startup
when missing — that is deliberate for hostnames, URLs, connection strings and
secrets (design-guideline shared-context: Configuration).
"""

from __future__ import annotations

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

    # --- Persistence --------------------------------------------------------
    database_url: PostgresDsn = Field(alias="DATABASE_URL")
    crawler_database_url: PostgresDsn | None = Field(default=None, alias="CRAWLER_DATABASE_URL")
    db_pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    db_statement_timeout_ms: int = Field(default=30_000, alias="DB_STATEMENT_TIMEOUT_MS")

    # --- Auth ---------------------------------------------------------------
    clerk_issuer: str = Field(alias="CLERK_ISSUER")
    clerk_audience: str = Field(alias="CLERK_AUDIENCE")
    clerk_jwks_url: str = Field(alias="CLERK_JWKS_URL")
    clerk_jwks_cache_seconds: int = Field(default=600, alias="CLERK_JWKS_CACHE_SECONDS")

    # --- Encryption ---------------------------------------------------------
    # Absent on the crawler by design; anything needing it fails loudly there.
    master_encryption_key: SecretStr | None = Field(default=None, alias="MASTER_ENCRYPTION_KEY")

    # --- Object storage -----------------------------------------------------
    s3_endpoint_url: str = Field(alias="S3_ENDPOINT_URL")
    s3_region: str = Field(alias="S3_REGION")
    s3_bucket: str = Field(alias="S3_BUCKET")
    s3_access_key_id: SecretStr = Field(alias="S3_ACCESS_KEY_ID")
    s3_secret_access_key: SecretStr = Field(alias="S3_SECRET_ACCESS_KEY")
    signed_url_ttl_seconds: int = Field(default=300, alias="SIGNED_URL_TTL_SECONDS")

    # --- Connector OAuth (separate from login OAuth) ------------------------
    oauth_redirect_base_url: str = Field(alias="OAUTH_REDIRECT_BASE_URL")
    github_oauth_client_id: str = Field(alias="GITHUB_OAUTH_CLIENT_ID")
    github_oauth_client_secret: SecretStr = Field(alias="GITHUB_OAUTH_CLIENT_SECRET")
    github_api_base_url: str = Field(alias="GITHUB_API_BASE_URL")
    jira_oauth_client_id: str = Field(alias="JIRA_OAUTH_CLIENT_ID")
    jira_oauth_client_secret: SecretStr = Field(alias="JIRA_OAUTH_CLIENT_SECRET")
    jira_api_base_url: str = Field(alias="JIRA_API_BASE_URL")
    jira_oauth_base_url: str = Field(alias="JIRA_OAUTH_BASE_URL")

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide settings object. Built once, on first call."""
    return Settings()
