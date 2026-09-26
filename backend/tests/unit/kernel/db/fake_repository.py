"""The six repository methods in memory, for unit tests of use cases.

The in-memory twin of ``kernel.db.repository.SqlAlchemyRepository``. It keeps
the same contract — newest first, the same paging rules, not-found errors from
``update`` and ``delete`` — so a use case tested against it behaves the same
against the database. It stores copies, so a use case that changes an entity
and forgets to save it is caught.

A component's fake names its entity's id and creation fields and says how its
filter matches; everything else is here.
"""

from __future__ import annotations

import copy
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

from kernel.errors import NotFoundError
from kernel.paging import check_page, offset_of

# The real clock, since use cases compare against it ("in the last day"), but
# strictly increasing, so "newest first" is deterministic in tests.
_last = datetime.min.replace(tzinfo=UTC)


def _now() -> datetime:
    global _last
    _last = max(datetime.now(UTC), _last + timedelta(microseconds=1))
    return _last


class FakeRepository[Entity, Filter](ABC):
    id_field: ClassVar[str] = "id"
    created_field: ClassVar[str] = "created_at"
    updated_field: ClassVar[str | None] = "updated_at"
    owner_field: ClassVar[str | None] = None
    noun: ClassVar[str] = "entity"

    def __init__(self, rows: dict[uuid.UUID, Any], *, owner_id: uuid.UUID | None = None) -> None:
        # Shared between every scope over the same store, like a table.
        self._rows = rows
        self._owner_id = owner_id

    @abstractmethod
    def matches(self, entity: Entity, filter: Filter) -> bool: ...

    async def create(self, entity: Entity) -> Entity:
        stored = copy.deepcopy(entity)
        now = _now()
        if getattr(stored, self.created_field) is None:
            setattr(stored, self.created_field, now)
        if self.updated_field is not None:
            setattr(stored, self.updated_field, now)
        self._rows[self._id(stored)] = stored
        return copy.deepcopy(stored)

    async def get(self, entity_id: uuid.UUID) -> Entity | None:
        found = self._visible().get(entity_id)
        return copy.deepcopy(found) if found is not None else None

    async def get_list(
        self, filter: Filter, page: int = 1, page_size: int | None = None
    ) -> list[Entity]:
        check_page(page, page_size)
        matching = sorted(
            (e for e in self._visible().values() if self.matches(e, filter)),
            key=lambda e: (getattr(e, self.created_field), self._id(e)),
            reverse=True,
        )
        if page_size is not None:
            start = offset_of(page, page_size)
            matching = matching[start : start + page_size]
        return [copy.deepcopy(e) for e in matching]

    async def get_count(self, filter: Filter) -> int:
        return sum(1 for e in self._visible().values() if self.matches(e, filter))

    async def update(self, entity: Entity) -> Entity:
        entity_id = self._id(entity)
        if entity_id not in self._visible():
            raise NotFoundError(f"{self.noun} not found", id=str(entity_id))
        stored = copy.deepcopy(entity)
        if self.updated_field is not None:
            setattr(stored, self.updated_field, _now())
        self._rows[entity_id] = stored
        return copy.deepcopy(stored)

    async def delete(self, entity_id: uuid.UUID) -> None:
        if entity_id not in self._visible():
            raise NotFoundError(f"{self.noun} not found", id=str(entity_id))
        del self._rows[entity_id]

    def _id(self, entity: Any) -> uuid.UUID:
        value: uuid.UUID = getattr(entity, self.id_field)
        return value

    def _visible(self) -> dict[uuid.UUID, Any]:
        if self._owner_id is None or self.owner_field is None:
            return self._rows
        owner = self.owner_field
        return {k: e for k, e in self._rows.items() if getattr(e, owner) == self._owner_id}
