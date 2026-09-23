"""Gap plans at the HTTP edge: queued with a status, refused in the envelope.

Runs the real routers and error handlers in-process against stand-in services —
no network, no infra, no queue.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import errors
from app.dependencies import current_user, get_container
from kernel.errors import TargetUnusableError
from modules.gapplan import api as gapplan_api
from modules.gapplan.public import PlanStatus, PlanSummaryView
from modules.target.api import router as target_router
from modules.target.public import TargetKind, TargetOptionView, TargetRef

PLAN_ID = uuid.uuid4()


def summary(ref: TargetRef, status: PlanStatus = PlanStatus.DRAFTING) -> PlanSummaryView:
    return PlanSummaryView(
        id=PLAN_ID,
        target=ref,
        label="Staff Platform Engineer · Meridian Labs",
        version=1,
        status=status,
        error_code=None,
        error_message=None,
        model_id=None,
        created_at=datetime(2026, 9, 23, tzinfo=UTC),
        drafted_at=None,
        progress=0,
    )


class FakeGapPlans:
    def __init__(self) -> None:
        self.refuse = False
        self.done: list[tuple[uuid.UUID, bool]] = []

    async def request(self, owner_id: uuid.UUID, ref: TargetRef) -> PlanSummaryView:
        if self.refuse:
            raise TargetUnusableError("nothing is known yet; paste its job description instead")
        return summary(ref)

    async def history(self, owner_id: uuid.UUID) -> list[PlanSummaryView]:
        return [summary(TargetRef(TargetKind.SUBSCRIPTION, str(uuid.uuid4())), PlanStatus.READY)]

    async def estimate_cost(self, owner_id: uuid.UUID, ref: TargetRef) -> dict[str, Any]:
        return {"cost_usd": "0.04", "model_id": "claude-opus-5", "kind": str(ref.kind)}

    async def set_task_done(self, owner_id: uuid.UUID, task_id: uuid.UUID, done: bool) -> None:
        self.done.append((task_id, done))


class FakeTargets:
    async def options(self, owner_id: uuid.UUID) -> list[TargetOptionView]:
        return [
            TargetOptionView(
                kind=TargetKind.SUBSCRIPTION,
                id=uuid.uuid4(),
                title="Senior Backend",
                role_name="Senior Backend Engineer",
                role_id=None,
                company_name="Kestrel Financial",
                fit=None,
                salary=None,
                source_kind="watchlist",
                url=None,
                subscription_id=None,
            )
        ]


@pytest.fixture
def plans() -> FakeGapPlans:
    return FakeGapPlans()


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def enqueue(name: str, **kwargs: Any) -> None:
        calls.append({"name": name, **kwargs})

    monkeypatch.setattr(gapplan_api, "enqueue", enqueue)
    return calls


@pytest.fixture
def client(plans: FakeGapPlans, queued: list[dict[str, Any]]) -> TestClient:
    app = FastAPI()
    errors.install(app)
    app.include_router(gapplan_api.router)
    app.include_router(target_router)
    user = uuid.uuid4()
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_container] = lambda: SimpleNamespace(
        gapplan=plans, target=FakeTargets()
    )
    return TestClient(app, raise_server_exceptions=False)


def test_requesting_a_plan_queues_it_and_returns_its_status(
    client: TestClient, queued: list[dict[str, Any]]
) -> None:
    target = str(uuid.uuid4())
    response = client.post("/gap-plans", json={"kind": "privatePosting", "id": target})

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "drafting"
    assert body["target"] == {"kind": "privatePosting", "id": target}
    assert [(job["name"], job["plan_id"]) for job in queued] == [("gapplan.draft", str(PLAN_ID))]


def test_a_target_that_cannot_be_planned_for_is_refused_before_anything_is_queued(
    client: TestClient, plans: FakeGapPlans, queued: list[dict[str, Any]]
) -> None:
    plans.refuse = True
    response = client.post("/gap-plans", json={"kind": "subscription", "id": str(uuid.uuid4())})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "target_unusable"
    assert queued == []


def test_an_unknown_target_kind_is_refused_in_the_envelope(client: TestClient) -> None:
    response = client.get(f"/gap-plans/cost-estimate?kind=linkedin&id={uuid.uuid4()}")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_the_estimate_is_for_the_target_asked_about(client: TestClient) -> None:
    response = client.get(f"/gap-plans/cost-estimate?kind=matchedPosting&id={uuid.uuid4()}")
    assert response.status_code == 200
    assert response.json()["kind"] == "matchedPosting"


def test_ticking_a_task_is_recorded(client: TestClient, plans: FakeGapPlans) -> None:
    task = uuid.uuid4()
    response = client.put(f"/gap-plan-tasks/{task}", json={"done": True})
    assert response.status_code == 204
    assert plans.done == [(task, True)]


def test_targets_say_where_each_one_came_from(client: TestClient) -> None:
    [option] = client.get("/targets").json()
    assert option["kind"] == "subscription"
    assert option["source_kind"] == "watchlist"
    assert option["label"] == "Senior Backend Engineer · Kestrel Financial"
