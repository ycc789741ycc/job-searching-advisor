"""The role map's unit of work over SQL: one owner-zone transaction per scope.

The scope opens ``Database.for_user`` — exactly the session the use cases used
to open themselves — so row-level security applies as before. Events recorded in
it go to the outbox in the same transaction, just before it commits.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, assert_never

from sqlalchemy.ext.asyncio import AsyncSession

from advisor.rolemap.domain import (
    RoleCountChanged,
    RoleMapEvent,
    RoleRequirementsChanged,
    RoleSplitOrMerged,
    RolesReclustered,
)
from advisor.rolemap.infra.repositories import (
    SqlAlchemyLineageEntryRepository,
    SqlAlchemyRoleMapSettingRepository,
    SqlAlchemyRoleMemberRepository,
    SqlAlchemyRoleRepository,
    SqlAlchemyRoleRequirementRepository,
)
from kernel.db import Database
from kernel.outbox import EventName, emit


class SqlAlchemyOwnerRoleMap:
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        self.roles = SqlAlchemyRoleRepository(session, owner_id=owner_id)
        self.members = SqlAlchemyRoleMemberRepository(session, owner_id=owner_id)
        self.requirements = SqlAlchemyRoleRequirementRepository(session, owner_id=owner_id)
        self.lineage = SqlAlchemyLineageEntryRepository(session, owner_id=owner_id)
        self.settings = SqlAlchemyRoleMapSettingRepository(session, owner_id=owner_id)
        self.pending: list[RoleMapEvent] = []

    def record(self, event: RoleMapEvent) -> None:
        self.pending.append(event)


class SqlAlchemyRoleMapUnitOfWork:
    def __init__(self, database: Database) -> None:
        self._db = database

    @asynccontextmanager
    async def for_owner(self, owner_id: uuid.UUID) -> AsyncIterator[SqlAlchemyOwnerRoleMap]:
        async with self._db.for_user(owner_id) as session:
            scope = SqlAlchemyOwnerRoleMap(session, owner_id)
            yield scope
            for event in scope.pending:
                name, payload, owner = _outbox_entry(event)
                await emit(session, name, payload, owner_id=owner)


def _outbox_entry(event: RoleMapEvent) -> tuple[EventName, dict[str, Any], uuid.UUID]:
    """The outbox name, payload and routing owner for each role-map event.

    These payloads are a contract with the dispatcher and must not drift.
    """
    match event:
        case RoleCountChanged():
            return (
                EventName.ROLE_COUNT_CHANGED,
                {"from": event.previous, "to": event.current},
                event.owner_id,
            )
        case RoleRequirementsChanged():
            return (
                EventName.ROLE_REQUIREMENTS_CHANGED,
                {"role_id": str(event.role_id), "requirements": event.requirements},
                event.owner_id,
            )
        case RoleSplitOrMerged():
            return (
                EventName.ROLE_SPLIT_OR_MERGED,
                {
                    "changes": [
                        {"kind": str(c.kind), "role_id": c.role_id, "from": list(c.from_role_ids)}
                        for c in event.changes
                    ]
                },
                event.owner_id,
            )
        case RolesReclustered():
            return EventName.ROLES_RECLUSTERED, {"roles": event.roles}, event.owner_id
        case _:
            assert_never(event)
