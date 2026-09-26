"""SQLAlchemy implementations of the profile's repositories.

The six methods come from ``kernel.db.repository.SqlAlchemyRepository``. Every
profile table is owner-zone, so every repository here is bound to one owner.
"""

from __future__ import annotations

import uuid
from typing import ClassVar

from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from advisor.profile.domain import (
    CareerPosition,
    CareerPositionFilter,
    Evidence,
    EvidenceFilter,
    ProfileVersion,
    ProfileVersionFilter,
    ResumeFile,
    ResumeFileFilter,
    ResumeStatus,
    SourceConnection,
    SourceConnectionFilter,
)
from advisor.profile.infra import mappers, models
from kernel.db.repository import SqlAlchemyRepository


class SqlAlchemySourceConnectionRepository(
    SqlAlchemyRepository[SourceConnection, models.SourceConnection, SourceConnectionFilter]
):
    model = models.SourceConnection
    id_column = models.SourceConnection.id
    created_column = models.SourceConnection.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = (
        models.SourceConnection.owner_id
    )
    noun = "connection"

    def to_entity(self, row: models.SourceConnection) -> SourceConnection:
        return mappers.connection(row)

    def to_row(self, entity: SourceConnection) -> models.SourceConnection:
        return mappers.connection_row(entity)

    def apply(self, row: models.SourceConnection, entity: SourceConnection) -> None:
        mappers.apply_connection(row, entity)

    def id_of(self, entity: SourceConnection) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: SourceConnectionFilter) -> list[ColumnElement[bool]]:
        if filter.kind is None:
            return []
        return [models.SourceConnection.kind == filter.kind]


class SqlAlchemyResumeFileRepository(
    SqlAlchemyRepository[ResumeFile, models.ResumeFile, ResumeFileFilter]
):
    model = models.ResumeFile
    id_column = models.ResumeFile.id
    created_column = models.ResumeFile.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.ResumeFile.owner_id
    noun = "resume"

    def to_entity(self, row: models.ResumeFile) -> ResumeFile:
        return mappers.resume_file(row)

    def to_row(self, entity: ResumeFile) -> models.ResumeFile:
        return mappers.resume_file_row(entity)

    def apply(self, row: models.ResumeFile, entity: ResumeFile) -> None:
        mappers.apply_resume_file(row, entity)

    def id_of(self, entity: ResumeFile) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: ResumeFileFilter) -> list[ColumnElement[bool]]:
        if filter.status is None:
            return []
        return [models.ResumeFile.status == str(filter.status)]

    async def get_latest_parsed(self) -> ResumeFile | None:
        resume = models.ResumeFile
        rows = await self._session.execute(
            self._select(ResumeFileFilter(status=ResumeStatus.PARSED))
            .order_by(resume.parsed_at.desc(), resume.id.desc())
            .limit(1)
        )
        row = rows.scalar_one_or_none()
        return mappers.resume_file(row) if row is not None else None


class SqlAlchemyEvidenceRepository(SqlAlchemyRepository[Evidence, models.Evidence, EvidenceFilter]):
    model = models.Evidence
    id_column = models.Evidence.id
    created_column = models.Evidence.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.Evidence.owner_id
    noun = "evidence"

    def to_entity(self, row: models.Evidence) -> Evidence:
        return mappers.evidence(row)

    def to_row(self, entity: Evidence) -> models.Evidence:
        return mappers.evidence_row(entity)

    def apply(self, row: models.Evidence, entity: Evidence) -> None:
        mappers.apply_evidence(row, entity)

    def id_of(self, entity: Evidence) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: EvidenceFilter) -> list[ColumnElement[bool]]:
        found: list[ColumnElement[bool]] = []
        if filter.source is not None:
            found.append(models.Evidence.source == str(filter.source))
        if filter.external_refs is not None:
            found.append(models.Evidence.external_ref.in_(filter.external_refs))
        return found


class SqlAlchemyCareerPositionRepository(
    SqlAlchemyRepository[CareerPosition, models.Position, CareerPositionFilter]
):
    model = models.Position
    id_column = models.Position.id
    created_column = models.Position.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.Position.owner_id
    noun = "position"

    def to_entity(self, row: models.Position) -> CareerPosition:
        return mappers.position(row)

    def to_row(self, entity: CareerPosition) -> models.Position:
        return mappers.position_row(entity)

    def apply(self, row: models.Position, entity: CareerPosition) -> None:
        mappers.apply_position(row, entity)

    def id_of(self, entity: CareerPosition) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: CareerPositionFilter) -> list[ColumnElement[bool]]:
        return []


class SqlAlchemyProfileVersionRepository(
    SqlAlchemyRepository[ProfileVersion, models.ProfileVersion, ProfileVersionFilter]
):
    model = models.ProfileVersion
    id_column = models.ProfileVersion.id
    # The table has no created_at; its one row per user is ordered by its bump.
    created_column = models.ProfileVersion.updated_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.ProfileVersion.owner_id
    noun = "profile version"

    def to_entity(self, row: models.ProfileVersion) -> ProfileVersion:
        return mappers.version(row)

    def to_row(self, entity: ProfileVersion) -> models.ProfileVersion:
        return mappers.version_row(entity)

    def apply(self, row: models.ProfileVersion, entity: ProfileVersion) -> None:
        mappers.apply_version(row, entity)

    def id_of(self, entity: ProfileVersion) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: ProfileVersionFilter) -> list[ColumnElement[bool]]:
        return []
