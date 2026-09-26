"""Role map HTTP surface: the bubble chart's roles."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from advisor.rolemap import MAX_ROLE_COUNT, MIN_ROLE_COUNT
from api.dependencies import CurrentUser, Deps
from wiring.queue import enqueue

router = APIRouter(tags=["rolemap"])


class RoleMapSettings(BaseModel):
    """How many roles the role map analyses on the user's key (ADR 0003)."""

    role_count: int = Field(ge=MIN_ROLE_COUNT, le=MAX_ROLE_COUNT)


@router.get("/roles")
async def list_roles(user: CurrentUser, deps: Deps) -> list[dict[str, object]]:
    return [
        {
            "id": str(role.id),
            "name": role.name,
            # X axis. `estimated` bubbles are drawn with a dashed outline,
            # because no real interview reports back them yet.
            "hiring_bar": role.hiring_bar,
            "bar_basis": role.bar_basis,
            "bar_confidence": role.bar_confidence,
            "bar_reasoning": role.bar_reasoning,
            "opening_count": role.opening_count,
            # Y axis, one band per market the user selected.
            "salary_bands": role.salary_bands,
            "is_coherent": role.is_coherent,
            "requirements": [
                {
                    "statement": r.statement,
                    "weight": r.weight,
                    "expected_level": r.expected_level,
                }
                for r in role.requirements
            ],
        }
        for role in await deps.rolemap.roles(user)
    ]


@router.get("/roles/settings")
async def get_settings(user: CurrentUser, deps: Deps) -> RoleMapSettings:
    return RoleMapSettings(role_count=await deps.rolemap.role_count(user))


@router.put("/roles/settings")
async def put_settings(body: RoleMapSettings, user: CurrentUser, deps: Deps) -> RoleMapSettings:
    """Saved only after the user confirmed the estimate for this k, so a change
    queues a recluster through ``RoleCountChanged``."""
    return RoleMapSettings(role_count=await deps.rolemap.set_role_count(user, body.role_count))


@router.get("/roles/cost-estimate")
async def cost_estimate(
    user: CurrentUser,
    deps: Deps,
    role_count: Annotated[int | None, Query(ge=MIN_ROLE_COUNT, le=MAX_ROLE_COUNT)] = None,
) -> dict[str, object]:
    """Shown before a role map runs, so nothing is spent unasked. Pass
    ``role_count`` to price a k before saving it; omit it for the saved k."""
    return await deps.rolemap.estimate_cost(user, role_count=role_count)


@router.post("/roles/recluster", status_code=202)
async def recluster(user: CurrentUser, deps: Deps) -> dict[str, str]:
    await enqueue("rolemap.recluster", owner_id=str(user))
    return {"status": "queued"}


__all__ = ["router"]
