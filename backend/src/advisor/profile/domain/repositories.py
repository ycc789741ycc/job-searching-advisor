"""How the profile's use cases reach stored data: interfaces in domain terms.

Every repository has the same six methods (ADR 0011): ``create``, ``get``,
``get_list`` (newest first, paged), ``get_count``, ``update`` and ``delete``,
over one frozen filter per aggregate whose unset fields do not filter. The one
extra method, ``ResumeFileRepository.get_latest_parsed``, is a non-default
order the six cannot express.

All profile data is owner-zone, so the unit of work has one scope: one user's
data, in one transaction. Events recorded in it are committed with it.
"""

from __future__ import annotations

import uuid
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from advisor.profile.domain.entities import (
    CareerPosition,
    ProfileVersion,
    ResumeFile,
    ResumeStatus,
    SourceConnection,
)
from advisor.profile.domain.events import ProfileEvent
from advisor.profile.domain.evidence import Evidence, EvidenceSource


class Repository[Entity, Filter](Protocol):
    """The six methods, as every profile repository has them."""

    async def create(self, entity: Entity) -> Entity: ...

    async def get(self, entity_id: uuid.UUID) -> Entity | None: ...

    async def get_list(
        self, filter: Filter, page: int = 1, page_size: int | None = None
    ) -> list[Entity]: ...

    async def get_count(self, filter: Filter) -> int: ...

    async def update(self, entity: Entity) -> Entity: ...

    async def delete(self, entity_id: uuid.UUID) -> None: ...


@dataclass(frozen=True, slots=True)
class SourceConnectionFilter:
    kind: str | None = None


class SourceConnectionRepository(
    Repository[SourceConnection, SourceConnectionFilter], Protocol
): ...


@dataclass(frozen=True, slots=True)
class ResumeFileFilter:
    status: ResumeStatus | None = None


class ResumeFileRepository(Repository[ResumeFile, ResumeFileFilter], Protocol):
    async def get_latest_parsed(self) -> ResumeFile | None:
        """The résumé parsed most recently.

        Extra method: it orders by when parsing finished, not by upload time,
        so a résumé re-parsed later counts as the latest.
        """
        ...


@dataclass(frozen=True, slots=True)
class EvidenceFilter:
    source: EvidenceSource | None = None
    external_refs: tuple[str, ...] | None = None


class EvidenceRepository(Repository[Evidence, EvidenceFilter], Protocol): ...


@dataclass(frozen=True, slots=True)
class CareerPositionFilter:
    """Nothing to filter on yet: a user's timeline is read whole."""


class CareerPositionRepository(Repository[CareerPosition, CareerPositionFilter], Protocol): ...


@dataclass(frozen=True, slots=True)
class ProfileVersionFilter:
    """One row per user; the owner scope is the only filter."""


class ProfileVersionRepository(Repository[ProfileVersion, ProfileVersionFilter], Protocol): ...


class OwnerProfile(Protocol):
    @property
    def connections(self) -> SourceConnectionRepository: ...

    @property
    def resumes(self) -> ResumeFileRepository: ...

    @property
    def evidence(self) -> EvidenceRepository: ...

    @property
    def positions(self) -> CareerPositionRepository: ...

    @property
    def versions(self) -> ProfileVersionRepository: ...

    def record(self, event: ProfileEvent) -> None: ...


class ProfileUnitOfWork(Protocol):
    def for_owner(self, owner_id: uuid.UUID) -> AbstractAsyncContextManager[OwnerProfile]: ...
