"""In-memory role-map storage: the domain's repository interfaces, with no database."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from advisor.rolemap.domain import (
    LineageEntry,
    LineageEntryFilter,
    Role,
    RoleFilter,
    RoleMapEvent,
    RoleMapSetting,
    RoleMapSettingFilter,
    RoleMember,
    RoleMemberFilter,
    RoleRequirement,
    RoleRequirementFilter,
)
from tests.unit.kernel.db.fake_repository import FakeRepository


@dataclass
class Store:
    roles: dict[uuid.UUID, Role] = field(default_factory=dict)
    members: dict[uuid.UUID, RoleMember] = field(default_factory=dict)
    requirements: dict[uuid.UUID, RoleRequirement] = field(default_factory=dict)
    lineage: dict[uuid.UUID, LineageEntry] = field(default_factory=dict)
    settings: dict[uuid.UUID, RoleMapSetting] = field(default_factory=dict)
    events: list[RoleMapEvent] = field(default_factory=list)


class FakeRoles(FakeRepository[Role, RoleFilter]):
    owner_field = "owner_id"
    noun = "role"

    def matches(self, entity: Role, filter: RoleFilter) -> bool:
        return filter.is_retired is None or (entity.retired_at is not None) == filter.is_retired


class FakeMembers(FakeRepository[RoleMember, RoleMemberFilter]):
    created_field = "id"
    updated_field = None
    owner_field = "owner_id"
    noun = "role member"

    def matches(self, entity: RoleMember, filter: RoleMemberFilter) -> bool:
        return filter.role_ids is None or entity.role_id in filter.role_ids


class FakeRequirements(FakeRepository[RoleRequirement, RoleRequirementFilter]):
    created_field = "id"
    updated_field = None
    owner_field = "owner_id"
    noun = "role requirement"

    def matches(self, entity: RoleRequirement, filter: RoleRequirementFilter) -> bool:
        return filter.role_ids is None or entity.role_id in filter.role_ids


class FakeLineage(FakeRepository[LineageEntry, LineageEntryFilter]):
    created_field = "recorded_at"
    updated_field = None
    owner_field = "owner_id"
    noun = "lineage entry"

    def matches(self, entity: LineageEntry, filter: LineageEntryFilter) -> bool:
        return filter.role_id is None or entity.role_id == filter.role_id


class FakeSettings(FakeRepository[RoleMapSetting, RoleMapSettingFilter]):
    owner_field = "owner_id"
    noun = "role map setting"

    def matches(self, entity: RoleMapSetting, filter: RoleMapSettingFilter) -> bool:
        return True


class FakeOwner:
    def __init__(self, store: Store, owner_id: uuid.UUID) -> None:
        self.roles = FakeRoles(store.roles, owner_id=owner_id)
        self.members = FakeMembers(store.members, owner_id=owner_id)
        self.requirements = FakeRequirements(store.requirements, owner_id=owner_id)
        self.lineage = FakeLineage(store.lineage, owner_id=owner_id)
        self.settings = FakeSettings(store.settings, owner_id=owner_id)
        self.pending: list[RoleMapEvent] = []

    def record(self, event: RoleMapEvent) -> None:
        self.pending.append(event)


class FakeRoleMapUnitOfWork:
    def __init__(self, store: Store | None = None) -> None:
        self.store = store or Store()

    @asynccontextmanager
    async def for_owner(self, owner_id: uuid.UUID) -> AsyncIterator[FakeOwner]:
        scope = FakeOwner(self.store, owner_id)
        yield scope
        self.store.events.extend(scope.pending)
