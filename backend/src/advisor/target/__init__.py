"""The target component.

Resolves what a plan or résumé aims at. It has no tables (ADR 0005).

This file is the component's public API. Everything else in the package is
private: other components, the delivery mechanisms and the composition root
import only what is listed here (import-linter contract
``target-public-surface``).
"""

from advisor.target._service import (
    DimensionGap,
    TargetKind,
    TargetOptionView,
    TargetPreview,
    TargetRef,
    TargetService,
    TargetSnapshot,
    UncoveredGap,
    requirements_block,
)

__all__ = [
    "DimensionGap",
    "TargetKind",
    "TargetOptionView",
    "TargetPreview",
    "TargetRef",
    "TargetService",
    "TargetSnapshot",
    "UncoveredGap",
    "requirements_block",
]
