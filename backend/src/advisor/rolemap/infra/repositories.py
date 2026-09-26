"""SQLAlchemy implementations of the role map's repositories.

The six methods come from ``kernel.db.repository.SqlAlchemyRepository``. Every
role-map table is owner-zone, so every repository here is bound to one owner.
Members and requirements have no creation time stored, so they sort by id.
"""

from __future__ import annotations

import uuid
from typing import ClassVar

from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from advisor.rolemap.domain import (
    LineageEntry,
    LineageEntryFilter,
    Role,
    RoleFilter,
    RoleMapSetting,
    RoleMapSettingFilter,
    RoleMember,
    RoleMemberFilter,
    RoleRequirement,
    RoleRequirementFilter,
)
from advisor.rolemap.infra import mappers, models
from kernel.db.repository import SqlAlchemyRepository


class SqlAlchemyRoleRepository(SqlAlchemyRepository[Role, models.Role, RoleFilter]):
    model = models.Role
    id_column = models.Role.id
    created_column = models.Role.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.Role.owner_id
    noun = "role"

    def to_entity(self, row: models.Role) -> Role:
        return mappers.role(row)

    def to_row(self, entity: Role) -> models.Role:
        return mappers.role_row(entity)

    def apply(self, row: models.Role, entity: Role) -> None:
        mappers.apply_role(row, entity)

    def id_of(self, entity: Role) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: RoleFilter) -> list[ColumnElement[bool]]:
        if filter.is_retired is True:
            return [models.Role.retired_at.is_not(None)]
        if filter.is_retired is False:
            return [models.Role.retired_at.is_(None)]
        return []


class SqlAlchemyRoleMemberRepository(
    SqlAlchemyRepository[RoleMember, models.RoleMember, RoleMemberFilter]
):
    model = models.RoleMember
    id_column = models.RoleMember.id
    created_column = models.RoleMember.id
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.RoleMember.owner_id
    noun = "role member"

    def to_entity(self, row: models.RoleMember) -> RoleMember:
        return mappers.member(row)

    def to_row(self, entity: RoleMember) -> models.RoleMember:
        return mappers.member_row(entity)

    def apply(self, row: models.RoleMember, entity: RoleMember) -> None:
        mappers.apply_member(row, entity)

    def id_of(self, entity: RoleMember) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: RoleMemberFilter) -> list[ColumnElement[bool]]:
        if filter.role_ids is None:
            return []
        return [models.RoleMember.role_id.in_(filter.role_ids)]


class SqlAlchemyRoleRequirementRepository(
    SqlAlchemyRepository[RoleRequirement, models.RoleRequirement, RoleRequirementFilter]
):
    model = models.RoleRequirement
    id_column = models.RoleRequirement.id
    created_column = models.RoleRequirement.id
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = (
        models.RoleRequirement.owner_id
    )
    noun = "role requirement"

    def to_entity(self, row: models.RoleRequirement) -> RoleRequirement:
        return mappers.requirement(row)

    def to_row(self, entity: RoleRequirement) -> models.RoleRequirement:
        return mappers.requirement_row(entity)

    def apply(self, row: models.RoleRequirement, entity: RoleRequirement) -> None:
        mappers.apply_requirement(row, entity)

    def id_of(self, entity: RoleRequirement) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: RoleRequirementFilter) -> list[ColumnElement[bool]]:
        if filter.role_ids is None:
            return []
        return [models.RoleRequirement.role_id.in_(filter.role_ids)]


class SqlAlchemyLineageEntryRepository(
    SqlAlchemyRepository[LineageEntry, models.RoleLineage, LineageEntryFilter]
):
    model = models.RoleLineage
    id_column = models.RoleLineage.id
    created_column = models.RoleLineage.recorded_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.RoleLineage.owner_id
    noun = "lineage entry"

    def to_entity(self, row: models.RoleLineage) -> LineageEntry:
        return mappers.lineage(row)

    def to_row(self, entity: LineageEntry) -> models.RoleLineage:
        return mappers.lineage_row(entity)

    def apply(self, row: models.RoleLineage, entity: LineageEntry) -> None:
        mappers.apply_lineage(row, entity)

    def id_of(self, entity: LineageEntry) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: LineageEntryFilter) -> list[ColumnElement[bool]]:
        if filter.role_id is None:
            return []
        return [models.RoleLineage.role_id == filter.role_id]


class SqlAlchemyRoleMapSettingRepository(
    SqlAlchemyRepository[RoleMapSetting, models.RoleMapSetting, RoleMapSettingFilter]
):
    model = models.RoleMapSetting
    id_column = models.RoleMapSetting.id
    created_column = models.RoleMapSetting.created_at
    owner_column: ClassVar[InstrumentedAttribute[uuid.UUID] | None] = models.RoleMapSetting.owner_id
    noun = "role map setting"

    def to_entity(self, row: models.RoleMapSetting) -> RoleMapSetting:
        return mappers.setting(row)

    def to_row(self, entity: RoleMapSetting) -> models.RoleMapSetting:
        return mappers.setting_row(entity)

    def apply(self, row: models.RoleMapSetting, entity: RoleMapSetting) -> None:
        mappers.apply_setting(row, entity)

    def id_of(self, entity: RoleMapSetting) -> uuid.UUID:
        return entity.id

    def conditions(self, filter: RoleMapSettingFilter) -> list[ColumnElement[bool]]:
        return []
