"""The rolemap component.

Roles clustered from postings, and the user's role map.

This file is the component's public API. Everything else in the package is
private: other components, the delivery mechanisms and the composition root
import only what is listed here (import-linter contract
``rolemap-public-surface``).
"""

from advisor.rolemap import _jobs as jobs
from advisor.rolemap._domain import (
    MAX_ROLE_COUNT,
    MIN_ROLE_COUNT,
)
from advisor.rolemap._service import (
    RequirementView,
    RoleMapService,
    RoleView,
)

__all__ = [
    "MAX_ROLE_COUNT",
    "MIN_ROLE_COUNT",
    "RequirementView",
    "RoleMapService",
    "RoleView",
    "jobs",
]
