"""Role-map use cases against in-memory storage: what they store and announce,
with no database, no model and no clustering."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from advisor.market import PostingView, Visibility
from advisor.rolemap import RoleMapService
from advisor.rolemap.domain import (
    DEFAULT_ROLE_COUNT,
    BarBasis,
    HiringBar,
    RoleChange,
    RoleCountChanged,
    RoleLineage,
    RoleRequirementsChanged,
    RoleSplitOrMerged,
    RolesReclustered,
    reconcile,
)
from advisor.rolemap.service import _RoleExtraction
from kernel.errors import ValidationError
from tests.unit.advisor.rolemap.fakes import FakeRoleMapUnitOfWork

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.UUID("00000000-0000-0000-0000-000000000002")


class FakeMarket:
    def __init__(self, postings: list[PostingView] | None = None) -> None:
        self.postings = postings or []

    async def markets(self, owner_id: uuid.UUID) -> list[str]:
        return []

    async def postings_in_scope(self, owner_id: uuid.UUID) -> list[PostingView]:
        return self.postings


def _service(uow: FakeRoleMapUnitOfWork, market: FakeMarket | None = None) -> RoleMapService:
    return RoleMapService(
        uow,
        market=market or FakeMarket(),  # type: ignore[arg-type]
        profile=None,  # type: ignore[arg-type]
        gateway=None,  # type: ignore[arg-type]
        embedding_model="test-model",
    )


def _posting(title: str) -> PostingView:
    return PostingView(
        id=uuid.uuid4(),
        company_name="Acme",
        title=title,
        location="Berlin",
        url=None,
        description="Build it.",
        visibility=Visibility.SHARED,
        salary=None,
    )


def _extraction(name: str, weights: tuple[float, ...] = (0.4, 0.9)) -> _RoleExtraction:
    return _RoleExtraction.model_validate(
        {
            "name": name,
            "requirements": [
                {"statement": f"skill {w}", "weight": w, "expected_level": "senior"}
                for w in weights
            ],
        }
    )


_BAR = HiringBar(value=70, confidence=0.6, basis=BarBasis.ESTIMATED, sample_size=0)


async def _store(
    service: RoleMapService, role_id: uuid.UUID, postings: list[PostingView], name: str
) -> None:
    await service._store_role(
        OWNER,
        role_id=role_id,
        keys={str(p.id) for p in postings},
        postings=postings,
        extraction=_extraction(name),
        bar=_BAR,
        bar_reasoning="because",
        model_id="model",
        template_version="v1",
    )


async def test_the_role_count_defaults_and_a_change_is_announced_once() -> None:
    uow = FakeRoleMapUnitOfWork()
    rolemap = _service(uow)

    assert await rolemap.role_count(OWNER) == DEFAULT_ROLE_COUNT
    await rolemap.set_role_count(OWNER, 5)
    await rolemap.set_role_count(OWNER, 5)

    assert await rolemap.role_count(OWNER) == 5
    assert await rolemap.role_count(OTHER) == DEFAULT_ROLE_COUNT
    assert uow.store.events == [
        RoleCountChanged(owner_id=OWNER, previous=DEFAULT_ROLE_COUNT, current=5)
    ]


async def test_a_role_count_outside_the_bounds_is_refused() -> None:
    with pytest.raises(ValidationError):
        await _service(FakeRoleMapUnitOfWork()).set_role_count(OWNER, 0)


async def test_storing_a_role_replaces_its_members_and_requirements() -> None:
    uow = FakeRoleMapUnitOfWork()
    postings = [_posting("Backend"), _posting("Platform")]
    rolemap = _service(uow, FakeMarket(postings))
    role_id = uuid.uuid4()

    await _store(rolemap, role_id, postings, "Backend Engineer")
    await _store(rolemap, role_id, postings[:1], "Senior Backend Engineer")

    [role] = await rolemap.roles(OWNER)
    assert role.name == "Senior Backend Engineer" and role.opening_count == 1
    assert role.hiring_bar == 70 and role.bar_basis == "estimated"
    # Weightiest requirement first, whatever order they were stored in.
    assert [r.weight for r in role.requirements] == [0.9, 0.4]
    assert len(uow.store.members) == 1 and len(uow.store.requirements) == 2
    [(same, members)] = await rolemap.role_postings(OWNER)
    assert same.id == role_id and [p.title for p in members] == ["Backend"]
    assert (
        uow.store.events
        == [RoleRequirementsChanged(owner_id=OWNER, role_id=role_id, requirements=2)] * 2
    )


async def test_keeping_a_role_refreshes_only_what_needs_no_model() -> None:
    uow = FakeRoleMapUnitOfWork()
    postings = [_posting("Backend"), _posting("Platform")]
    rolemap = _service(uow, FakeMarket(postings))
    role_id = uuid.uuid4()
    await _store(rolemap, role_id, postings[:1], "Backend Engineer")

    assert await rolemap._keep_role(OWNER, role_id=role_id, postings=postings)
    assert not await rolemap._keep_role(OWNER, role_id=uuid.uuid4(), postings=postings)

    [role] = await rolemap.roles(OWNER)
    assert role.opening_count == 2 and role.name == "Backend Engineer"


async def test_lineage_retires_what_is_gone_and_announces_splits() -> None:
    uow = FakeRoleMapUnitOfWork()
    rolemap = _service(uow)
    kept, gone = uuid.uuid4(), uuid.uuid4()
    await _store(rolemap, kept, [_posting("Backend")], "Backend")
    await _store(rolemap, gone, [_posting("Data")], "Data")
    uow.store.events.clear()

    reconciliation: Any = reconcile(
        previous={str(kept): {"a", "b", "c", "d"}, str(gone): {"x", "y"}},
        clusters=[{"a", "b"}, {"c", "d"}],
        new_id=lambda: str(uuid.uuid4()),
    )
    await rolemap._record_lineage(OWNER, reconciliation)

    assert [r.id for r in await rolemap.roles(OWNER)] == [kept]
    assert len(uow.store.lineage) == len(reconciliation.lineage)
    splits = tuple(
        e for e in reconciliation.lineage if e.kind in (RoleChange.SPLIT, RoleChange.MERGED)
    )
    expected: list[Any] = [RoleSplitOrMerged(owner_id=OWNER, changes=splits)] if splits else []
    expected.append(RolesReclustered(owner_id=OWNER, roles=2))
    assert uow.store.events == expected
    assert all(isinstance(e, RoleLineage) for e in splits)
