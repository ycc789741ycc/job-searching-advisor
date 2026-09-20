"""Role map HTTP surface: the bubble chart's roles."""

from __future__ import annotations

from fastapi import APIRouter

from app.dependencies import CurrentUser, Deps
from app.queue import enqueue

router = APIRouter(tags=["rolemap"])


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


@router.get("/roles/cost-estimate")
async def cost_estimate(user: CurrentUser, deps: Deps) -> dict[str, object]:
    """Shown before the first role map, so nothing is spent unasked."""
    return await deps.rolemap.estimate_cost(user)


@router.post("/roles/recluster", status_code=202)
async def recluster(user: CurrentUser, deps: Deps) -> dict[str, str]:
    await enqueue("rolemap.recluster", owner_id=str(user))
    return {"status": "queued"}


__all__ = ["router"]
