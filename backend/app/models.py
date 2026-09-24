"""Imports every ORM model so ``Base.metadata`` is complete.

Alembic and the integration-test harness both need one place that knows about
all of them. Nothing else should import this.
"""

from __future__ import annotations

from kernel.db.base import Base
from kernel.outbox.models import OutboxEvent  # noqa: F401
from modules.assessment.infra.models import (  # noqa: F401
    DimensionLineage,
    DimensionScore,
    FollowUpQuestion,
    RoleFit,
    SkillAssessment,
    SkillDimension,
)
from modules.gapplan.infra.models import GapPlan, Milestone, Task  # noqa: F401
from modules.identity.infra.models import (  # noqa: F401
    Account,
    AiUsageBudget,
    AiUsageLedger,
    FederatedIdentity,
    PasswordCredential,
    ProviderCredential,
    RefreshToken,
)
from modules.market.infra.models import (  # noqa: F401
    Company,
    CompanySubscription,
    CrawlSource,
    JobPosting,
    ManualRefreshLog,
    MarketPreference,
    PostingEmbedding,
    PrivateJobPosting,
)
from modules.profile.infra.models import (  # noqa: F401
    Evidence,
    Position,
    ProfileVersion,
    ResumeFile,
    SourceConnection,
)
from modules.resume.infra.models import Export, Resume, ResumeVersion, Revision  # noqa: F401
from modules.rolemap.infra.models import (  # noqa: F401
    Role,
    RoleLineage,
    RoleMapSetting,
    RoleMember,
    RoleRequirement,
)

# Schemas, in the order they are created.
SCHEMAS = (
    "identity",
    "profile",
    "market",
    "market_user",
    "rolemap",
    "assessment",
    "gapplan",
    "resume",
    "outbox",
)

# Every table with an owner_id, covered by row-level security.
#
# `outbox` is excluded on purpose. Its `owner_id` is a routing hint, not a
# tenancy boundary: the crawler writes rows with no owner at all (it must not
# know which users a market change affects), and the dispatcher has to read
# every row to fan them out. Tenancy there is enforced by the grants instead —
# the crawler role may only INSERT and SELECT on it.
OWNER_ZONE_TABLES = tuple(
    name
    for name, table in sorted(Base.metadata.tables.items())
    if "owner_id" in table.columns and not name.startswith("outbox.")
)

# Shared zone: no owner_id, reachable by the crawler role.
SHARED_MARKET_TABLES = (
    "market.company",
    "market.crawl_source",
    "market.job_posting",
    "market.posting_embedding",
)

metadata = Base.metadata

__all__ = ["OWNER_ZONE_TABLES", "SCHEMAS", "SHARED_MARKET_TABLES", "Base", "metadata"]
