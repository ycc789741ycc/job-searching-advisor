"""What the role map tells the rest of the system, as domain facts.

``advisor.rolemap.infra`` maps each to its outbox name and payload.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from advisor.rolemap.domain.identity import RoleLineage


@dataclass(frozen=True, slots=True)
class RoleCountChanged:
    owner_id: uuid.UUID
    previous: int
    current: int


@dataclass(frozen=True, slots=True)
class RoleRequirementsChanged:
    owner_id: uuid.UUID
    role_id: uuid.UUID
    requirements: int


@dataclass(frozen=True, slots=True)
class RoleSplitOrMerged:
    owner_id: uuid.UUID
    changes: tuple[RoleLineage, ...]


@dataclass(frozen=True, slots=True)
class RolesReclustered:
    owner_id: uuid.UUID
    roles: int


RoleMapEvent = RoleCountChanged | RoleRequirementsChanged | RoleSplitOrMerged | RolesReclustered
