"""The role map's k at the HTTP edge: bounded, and refused in the one envelope.

Runs the real router and error handlers in-process against a stand-in service —
no network, no infra.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from advisor.rolemap._domain import DEFAULT_ROLE_COUNT, MAX_ROLE_COUNT, MIN_ROLE_COUNT
from api import errors
from api.dependencies import current_user, get_container
from api.routes.rolemap import router


class FakeRoleMap:
    def __init__(self) -> None:
        self.stored = DEFAULT_ROLE_COUNT
        self.estimated_for: list[int | None] = []

    async def role_count(self, owner_id: uuid.UUID) -> int:
        return self.stored

    async def set_role_count(self, owner_id: uuid.UUID, role_count: int) -> int:
        self.stored = role_count
        return role_count

    async def estimate_cost(
        self, owner_id: uuid.UUID, *, role_count: int | None = None
    ) -> dict[str, Any]:
        self.estimated_for.append(role_count)
        return {"max_clusters": role_count or self.stored, "cost_usd": "0"}


@pytest.fixture
def rolemap() -> FakeRoleMap:
    return FakeRoleMap()


@pytest.fixture
def client(rolemap: FakeRoleMap) -> TestClient:
    app = FastAPI()
    errors.install(app)
    app.include_router(router)
    user = uuid.uuid4()
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_container] = lambda: SimpleNamespace(rolemap=rolemap)
    return TestClient(app, raise_server_exceptions=False)


def test_an_unset_k_reads_as_the_default(client: TestClient) -> None:
    assert client.get("/roles/settings").json() == {"role_count": DEFAULT_ROLE_COUNT}


def test_a_k_inside_the_bound_is_saved(client: TestClient, rolemap: FakeRoleMap) -> None:
    response = client.put("/roles/settings", json={"role_count": MAX_ROLE_COUNT})
    assert response.status_code == 200
    assert rolemap.stored == MAX_ROLE_COUNT


@pytest.mark.parametrize("role_count", [MIN_ROLE_COUNT - 1, MAX_ROLE_COUNT + 1])
def test_a_k_outside_the_bound_is_refused_in_the_envelope(
    client: TestClient, rolemap: FakeRoleMap, role_count: int
) -> None:
    response = client.put("/roles/settings", json={"role_count": role_count})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert error["message"].startswith("role_count:")
    assert rolemap.stored == DEFAULT_ROLE_COUNT


def test_the_estimate_can_price_a_k_before_it_is_saved(
    client: TestClient, rolemap: FakeRoleMap
) -> None:
    response = client.get("/roles/cost-estimate", params={"role_count": 15})
    assert response.status_code == 200
    assert rolemap.estimated_for == [15]
    assert rolemap.stored == DEFAULT_ROLE_COUNT


def test_the_estimate_refuses_a_proposed_k_outside_the_bound(client: TestClient) -> None:
    response = client.get("/roles/cost-estimate", params={"role_count": MAX_ROLE_COUNT + 1})
    assert response.status_code == 422
