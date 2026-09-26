"""The profile component.

The CareerProfile: career timeline and evidence from connectors and uploaded
résumés.

This file is the component's public API. Everything else in the package is
private: other components, the delivery mechanisms and the composition root
import only what is listed here (import-linter contract
``profile-public-surface``).
"""

from advisor.profile import jobs
from advisor.profile.factory import create_profile_service
from advisor.profile.infra.connectors import (
    GitHubConnector,
    JiraConnector,
)
from advisor.profile.infra.connectors.github import (
    SCOPE_DESCRIPTIONS as GITHUB_SCOPE_DESCRIPTIONS,
)
from advisor.profile.infra.connectors.jira import (
    SCOPE_DESCRIPTIONS as JIRA_SCOPE_DESCRIPTIONS,
)
from advisor.profile.infra.oauth import (
    authorize_url,
    exchange_code,
    sign_state,
    verify_state,
)
from advisor.profile.service import (
    ACCEPTED_TYPES,
    CitationError,
    ConnectionView,
    EvidenceSource,
    EvidenceView,
    ProfileService,
    ProfileSnapshot,
    ResumeFileView,
    assert_citations_exist,
)

__all__ = [
    "ACCEPTED_TYPES",
    "GITHUB_SCOPE_DESCRIPTIONS",
    "JIRA_SCOPE_DESCRIPTIONS",
    "CitationError",
    "ConnectionView",
    "EvidenceSource",
    "EvidenceView",
    "GitHubConnector",
    "JiraConnector",
    "ProfileService",
    "ProfileSnapshot",
    "ResumeFileView",
    "assert_citations_exist",
    "authorize_url",
    "create_profile_service",
    "exchange_code",
    "jobs",
    "sign_state",
    "verify_state",
]
