"""The profile's unit of work over SQL: one owner-zone transaction per scope.

The scope opens exactly the session the use cases used to open themselves —
``Database.for_user`` — so row-level security applies as before. Events
recorded in it go to the outbox in the same transaction, just before it commits.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, assert_never

from sqlalchemy.ext.asyncio import AsyncSession

from advisor.profile.domain import ProfileEvent, ProfileUpdated, SourceSynced
from advisor.profile.infra.repositories import (
    SqlAlchemyCareerPositionRepository,
    SqlAlchemyEvidenceRepository,
    SqlAlchemyProfileVersionRepository,
    SqlAlchemyResumeFileRepository,
    SqlAlchemySourceConnectionRepository,
)
from kernel.db import Database
from kernel.outbox import EventName, emit


class SqlAlchemyOwnerProfile:
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        self.connections = SqlAlchemySourceConnectionRepository(session, owner_id=owner_id)
        self.resumes = SqlAlchemyResumeFileRepository(session, owner_id=owner_id)
        self.evidence = SqlAlchemyEvidenceRepository(session, owner_id=owner_id)
        self.positions = SqlAlchemyCareerPositionRepository(session, owner_id=owner_id)
        self.versions = SqlAlchemyProfileVersionRepository(session, owner_id=owner_id)
        self.pending: list[ProfileEvent] = []

    def record(self, event: ProfileEvent) -> None:
        self.pending.append(event)


class SqlAlchemyProfileUnitOfWork:
    def __init__(self, database: Database) -> None:
        self._db = database

    @asynccontextmanager
    async def for_owner(self, owner_id: uuid.UUID) -> AsyncIterator[SqlAlchemyOwnerProfile]:
        async with self._db.for_user(owner_id) as session:
            scope = SqlAlchemyOwnerProfile(session, owner_id)
            yield scope
            for event in scope.pending:
                name, payload, owner = _outbox_entry(event)
                await emit(session, name, payload, owner_id=owner)


def _outbox_entry(event: ProfileEvent) -> tuple[EventName, dict[str, Any], uuid.UUID]:
    """The outbox name, payload and routing owner for each profile event.

    These payloads are a contract with the dispatcher and must not drift.
    """
    match event:
        case SourceSynced():
            return (
                EventName.SOURCE_SYNCED,
                {"kind": event.kind, "evidence": event.evidence},
                event.owner_id,
            )
        case ProfileUpdated():
            return (
                EventName.PROFILE_UPDATED,
                {"source": str(event.source), "version": event.version, "count": event.count},
                event.owner_id,
            )
        case _:
            assert_never(event)
