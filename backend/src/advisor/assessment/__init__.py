"""The assessment component.

The strength report: skill dimensions, role fits and follow-up questions.

This file is the component's public API. Everything else in the package is
private: other components, the delivery mechanisms and the composition root
import only what is listed here (import-linter contract
``assessment-public-surface``).
"""

from advisor.assessment import _jobs as jobs
from advisor.assessment._domain import (
    DEFAULT_MATCHES,
    MAX_MATCHES,
    MIN_MATCHES,
)
from advisor.assessment._service import (
    AssessmentService,
    AssessmentView,
    DimensionView,
    FitView,
    MatchedPostingView,
    QuestionView,
)

__all__ = [
    "DEFAULT_MATCHES",
    "MAX_MATCHES",
    "MIN_MATCHES",
    "AssessmentService",
    "AssessmentView",
    "DimensionView",
    "FitView",
    "MatchedPostingView",
    "QuestionView",
    "jobs",
]
