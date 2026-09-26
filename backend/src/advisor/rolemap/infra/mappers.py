"""ORM rows to role-map entities and back. No rules live here, only shape."""

from __future__ import annotations

from advisor.rolemap.domain import (
    LineageEntry,
    Role,
    RoleChange,
    RoleMapSetting,
    RoleMember,
    RoleRequirement,
)
from advisor.rolemap.infra import models


def role(row: models.Role) -> Role:
    return Role(
        id=row.id,
        owner_id=row.owner_id,
        name=row.name,
        is_coherent=row.is_coherent,
        opening_count=row.opening_count,
        hiring_bar=row.hiring_bar,
        bar_confidence=row.bar_confidence,
        bar_basis=row.bar_basis,
        bar_sample_size=row.bar_sample_size,
        bar_reasoning=row.bar_reasoning,
        salary_bands=dict(row.salary_bands or {}),
        model_id=row.model_id,
        template_version=row.template_version,
        retired_at=row.retired_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def role_row(entity: Role) -> models.Role:
    row = models.Role(id=entity.id, owner_id=entity.owner_id)
    apply_role(row, entity)
    return row


def apply_role(row: models.Role, entity: Role) -> None:
    row.name = entity.name
    row.is_coherent = entity.is_coherent
    row.opening_count = entity.opening_count
    row.hiring_bar = entity.hiring_bar
    row.bar_confidence = entity.bar_confidence
    row.bar_basis = entity.bar_basis
    row.bar_sample_size = entity.bar_sample_size
    row.bar_reasoning = entity.bar_reasoning
    row.salary_bands = dict(entity.salary_bands)
    row.model_id = entity.model_id
    row.template_version = entity.template_version
    row.retired_at = entity.retired_at


def member(row: models.RoleMember) -> RoleMember:
    return RoleMember(
        id=row.id, owner_id=row.owner_id, role_id=row.role_id, posting_key=row.posting_key
    )


def member_row(entity: RoleMember) -> models.RoleMember:
    return models.RoleMember(
        id=entity.id,
        owner_id=entity.owner_id,
        role_id=entity.role_id,
        posting_key=entity.posting_key,
    )


def apply_member(row: models.RoleMember, entity: RoleMember) -> None:
    row.role_id = entity.role_id
    row.posting_key = entity.posting_key


def requirement(row: models.RoleRequirement) -> RoleRequirement:
    return RoleRequirement(
        id=row.id,
        owner_id=row.owner_id,
        role_id=row.role_id,
        statement=row.statement,
        weight=row.weight,
        expected_level=row.expected_level,
    )


def requirement_row(entity: RoleRequirement) -> models.RoleRequirement:
    row = models.RoleRequirement(id=entity.id, owner_id=entity.owner_id, role_id=entity.role_id)
    apply_requirement(row, entity)
    return row


def apply_requirement(row: models.RoleRequirement, entity: RoleRequirement) -> None:
    row.statement = entity.statement
    row.weight = entity.weight
    row.expected_level = entity.expected_level


def lineage(row: models.RoleLineage) -> LineageEntry:
    return LineageEntry(
        id=row.id,
        owner_id=row.owner_id,
        role_id=row.role_id,
        kind=RoleChange(row.kind),
        from_role_ids=tuple(row.from_role_ids),
        recorded_at=row.recorded_at,
    )


def lineage_row(entity: LineageEntry) -> models.RoleLineage:
    row = models.RoleLineage(id=entity.id, owner_id=entity.owner_id)
    apply_lineage(row, entity)
    return row


def apply_lineage(row: models.RoleLineage, entity: LineageEntry) -> None:
    row.role_id = entity.role_id
    row.kind = str(entity.kind)
    row.from_role_ids = list(entity.from_role_ids)


def setting(row: models.RoleMapSetting) -> RoleMapSetting:
    return RoleMapSetting(
        id=row.id,
        owner_id=row.owner_id,
        role_count=row.role_count,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def setting_row(entity: RoleMapSetting) -> models.RoleMapSetting:
    return models.RoleMapSetting(
        id=entity.id, owner_id=entity.owner_id, role_count=entity.role_count
    )


def apply_setting(row: models.RoleMapSetting, entity: RoleMapSetting) -> None:
    row.role_count = entity.role_count
