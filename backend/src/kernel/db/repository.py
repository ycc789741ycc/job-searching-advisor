"""The six repository methods, written once for SQLAlchemy.

Every repository has the same shape — ``create``, ``get``, ``get_list``,
``get_count``, ``update``, ``delete`` (design guideline, data access; ADR 0011).
A component's SQLAlchemy repository subclasses this and supplies only what is
particular to its aggregate: the model, the mapping both ways, and how each
filter field becomes a condition.

Lists are newest first — ``created_at`` descending, ties broken by id
descending — so pages are stable. A repository bound to an owner adds
``owner_id = :owner`` to every read and write. Row-level security already
enforces that; the condition keeps the rule visible and the plans honest.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from kernel.db.base import Base
from kernel.errors import NotFoundError
from kernel.paging import check_page, offset_of


class SqlAlchemyRepository[Entity, Row: Base, Filter](ABC):
    # Column attributes are SQLAlchemy descriptors: read them from the class,
    # never through ``self``, or they bind to the repository as if it were a row.
    model: ClassVar[type[Any]]
    id_column: ClassVar[InstrumentedAttribute[Any]]
    # When the aggregate was created; lists sort on it, newest first.
    created_column: ClassVar[InstrumentedAttribute[Any]]
    # Names the aggregate in a not-found error.
    noun: ClassVar[str]
    # Set on repositories over owner-zone tables.
    owner_column: ClassVar[InstrumentedAttribute[Any] | None] = None

    def __init__(self, session: AsyncSession, *, owner_id: uuid.UUID | None = None) -> None:
        self._session = session
        self._owner_id = owner_id

    # --- what a subclass supplies ------------------------------------------

    @abstractmethod
    def to_entity(self, row: Row) -> Entity: ...

    @abstractmethod
    def to_row(self, entity: Entity) -> Row: ...

    @abstractmethod
    def apply(self, row: Row, entity: Entity) -> None:
        """Copy an entity's state onto its stored row."""
        ...

    @abstractmethod
    def id_of(self, entity: Entity) -> uuid.UUID: ...

    @abstractmethod
    def conditions(self, filter: Filter) -> list[ColumnElement[bool]]:
        """One condition per set filter field; they combine with AND."""
        ...

    # --- the six methods ---------------------------------------------------

    async def create(self, entity: Entity) -> Entity:
        row = self.to_row(entity)
        self._session.add(row)
        await self._session.flush()
        return self.to_entity(row)

    async def get(self, entity_id: uuid.UUID) -> Entity | None:
        row = await self._row(entity_id)
        return self.to_entity(row) if row is not None else None

    async def get_list(
        self, filter: Filter, page: int = 1, page_size: int | None = None
    ) -> list[Entity]:
        check_page(page, page_size)
        cls = type(self)
        query = self._select(filter).order_by(cls.created_column.desc(), cls.id_column.desc())
        if page_size is not None:
            query = query.limit(page_size).offset(offset_of(page, page_size))
        rows = await self._session.execute(query)
        return [self.to_entity(row) for row in rows.scalars()]

    async def get_count(self, filter: Filter) -> int:
        query = (
            select(func.count())
            .select_from(self.model)
            .where(*self._owner_conditions(), *self.conditions(filter))
        )
        return int((await self._session.execute(query)).scalar_one())

    async def update(self, entity: Entity) -> Entity:
        row = await self._row(self.id_of(entity))
        if row is None:
            raise NotFoundError(f"{self.noun} not found", id=str(self.id_of(entity)))
        self.apply(row, entity)
        await self._session.flush()
        return self.to_entity(row)

    async def delete(self, entity_id: uuid.UUID) -> None:
        row = await self._row(entity_id)
        if row is None:
            raise NotFoundError(f"{self.noun} not found", id=str(entity_id))
        await self._session.delete(row)
        await self._session.flush()

    # --- helpers for subclasses --------------------------------------------

    def _select(self, filter: Filter) -> Select[tuple[Row]]:
        return select(self.model).where(*self._owner_conditions(), *self.conditions(filter))

    def _owner_conditions(self) -> list[ColumnElement[bool]]:
        owner = type(self).owner_column
        if self._owner_id is None or owner is None:
            return []
        return [owner == self._owner_id]

    async def _row(self, entity_id: uuid.UUID) -> Row | None:
        row: Row | None = await self._session.get(self.model, entity_id)
        if row is None:
            return None
        owner = type(self).owner_column
        if self._owner_id is not None and owner is not None:
            if getattr(row, owner.key) != self._owner_id:
                return None
        return row
