"""The role map's entities: roles, what they were built from and require, how
they changed, and the user's chosen role count.

Plain data with the rules that belong to it; ``advisor.rolemap.infra`` maps
these to and from the database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from advisor.rolemap.domain.hiring_bar import HiringBar
from advisor.rolemap.domain.identity import RoleChange


@dataclass(slots=True)
class Role:
    """A cluster of postings in one user's markets.

    ``id`` is stable across re-clustering: goals and fits point at it, so
    renumbering on every crawl would break them.
    """

    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    is_coherent: bool = True
    opening_count: int = 0
    hiring_bar: int = 50
    bar_confidence: float = 0.0
    bar_basis: str = "estimated"
    bar_sample_size: int = 0
    bar_reasoning: str | None = None
    salary_bands: dict[str, Any] = field(default_factory=dict)
    model_id: str | None = None
    template_version: str | None = None
    retired_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def refresh_market(self, *, opening_count: int, salary_bands: dict[str, Any]) -> None:
        """Keep an analysed role, refreshing only what needs no AI."""
        self.opening_count = opening_count
        self.salary_bands = salary_bands
        self.retired_at = None

    def analysed(
        self,
        *,
        name: str,
        is_coherent: bool,
        opening_count: int,
        bar: HiringBar,
        bar_reasoning: str,
        salary_bands: dict[str, Any],
        model_id: str,
        template_version: str,
    ) -> None:
        self.name = name
        self.is_coherent = is_coherent
        self.opening_count = opening_count
        self.hiring_bar = bar.value
        self.bar_confidence = bar.confidence
        self.bar_basis = str(bar.basis)
        self.bar_sample_size = bar.sample_size
        self.bar_reasoning = bar_reasoning
        self.salary_bands = salary_bands
        self.model_id = model_id
        self.template_version = template_version
        self.retired_at = None

    def retire(self, at: datetime) -> None:
        self.retired_at = at


@dataclass(slots=True)
class RoleMember:
    """One posting a role was built from, by its clustering key."""

    id: uuid.UUID
    owner_id: uuid.UUID
    role_id: uuid.UUID
    posting_key: str


@dataclass(slots=True)
class RoleRequirement:
    """Free text pulled from a role's postings. It has no dimension."""

    id: uuid.UUID
    owner_id: uuid.UUID
    role_id: uuid.UUID
    statement: str
    weight: float
    expected_level: str


@dataclass(slots=True)
class LineageEntry:
    """A recorded change to a role — added, split, merged, retired — with the
    roles it came from, so a goal can find a split role's successor."""

    id: uuid.UUID
    owner_id: uuid.UUID
    role_id: uuid.UUID
    kind: RoleChange
    from_role_ids: tuple[str, ...]
    recorded_at: datetime | None = None


@dataclass(slots=True)
class RoleMapSetting:
    """How many roles this user's role map analyses (ADR 0003)."""

    id: uuid.UUID
    owner_id: uuid.UUID
    role_count: int
    created_at: datetime | None = None
    updated_at: datetime | None = None
