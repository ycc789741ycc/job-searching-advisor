"""In-memory profile storage: the domain's repository interfaces, with no database."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from advisor.profile.domain import (
    CareerPosition,
    CareerPositionFilter,
    Evidence,
    EvidenceFilter,
    ProfileEvent,
    ProfileVersion,
    ProfileVersionFilter,
    ResumeFile,
    ResumeFileFilter,
    ResumeStatus,
    SourceConnection,
    SourceConnectionFilter,
)
from tests.unit.kernel.db.fake_repository import FakeRepository


@dataclass
class Store:
    connections: dict[uuid.UUID, SourceConnection] = field(default_factory=dict)
    resumes: dict[uuid.UUID, ResumeFile] = field(default_factory=dict)
    evidence: dict[uuid.UUID, Evidence] = field(default_factory=dict)
    positions: dict[uuid.UUID, CareerPosition] = field(default_factory=dict)
    versions: dict[uuid.UUID, ProfileVersion] = field(default_factory=dict)
    events: list[ProfileEvent] = field(default_factory=list)


class FakeConnections(FakeRepository[SourceConnection, SourceConnectionFilter]):
    owner_field = "owner_id"
    noun = "connection"

    def matches(self, entity: SourceConnection, filter: SourceConnectionFilter) -> bool:
        return filter.kind is None or entity.kind == filter.kind


class FakeResumes(FakeRepository[ResumeFile, ResumeFileFilter]):
    owner_field = "owner_id"
    noun = "resume"

    def matches(self, entity: ResumeFile, filter: ResumeFileFilter) -> bool:
        return filter.status is None or entity.status == filter.status

    async def get_latest_parsed(self) -> ResumeFile | None:
        parsed = [
            r
            for r in await self.get_list(ResumeFileFilter(status=ResumeStatus.PARSED))
            if r.parsed_at is not None
        ]
        return max(parsed, key=lambda r: (r.parsed_at, r.id), default=None)


class FakeEvidence(FakeRepository[Evidence, EvidenceFilter]):
    owner_field = "owner_id"
    noun = "evidence"

    def matches(self, entity: Evidence, filter: EvidenceFilter) -> bool:
        return (filter.source is None or entity.source == filter.source) and (
            filter.external_refs is None or entity.external_ref in filter.external_refs
        )


class FakePositions(FakeRepository[CareerPosition, CareerPositionFilter]):
    owner_field = "owner_id"
    noun = "position"

    def matches(self, entity: CareerPosition, filter: CareerPositionFilter) -> bool:
        return True


class FakeVersions(FakeRepository[ProfileVersion, ProfileVersionFilter]):
    created_field = "updated_at"
    updated_field = None
    owner_field = "owner_id"
    noun = "profile version"

    def matches(self, entity: ProfileVersion, filter: ProfileVersionFilter) -> bool:
        return True


class FakeOwner:
    def __init__(self, store: Store, owner_id: uuid.UUID) -> None:
        self.connections = FakeConnections(store.connections, owner_id=owner_id)
        self.resumes = FakeResumes(store.resumes, owner_id=owner_id)
        self.evidence = FakeEvidence(store.evidence, owner_id=owner_id)
        self.positions = FakePositions(store.positions, owner_id=owner_id)
        self.versions = FakeVersions(store.versions, owner_id=owner_id)
        self.pending: list[ProfileEvent] = []

    def record(self, event: ProfileEvent) -> None:
        self.pending.append(event)


class FakeProfileUnitOfWork:
    def __init__(self, store: Store | None = None) -> None:
        self.store = store or Store()

    @asynccontextmanager
    async def for_owner(self, owner_id: uuid.UUID) -> AsyncIterator[FakeOwner]:
        scope = FakeOwner(self.store, owner_id)
        yield scope
        self.store.events.extend(scope.pending)


class FakeObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, content: bytes, content_type: str) -> None:
        self.objects[key] = content

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def signed_url(self, key: str) -> str:
        return f"https://objects.test/{key}"
