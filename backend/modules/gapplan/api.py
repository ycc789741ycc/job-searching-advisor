"""Gap plan HTTP surface: plan a route to a Target, then work through it."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.dependencies import CurrentUser, Deps
from app.queue import enqueue
from modules.gapplan.public import PlanSummaryView, PlanView
from modules.target.public import TargetKind, TargetRef

router = APIRouter(tags=["gapplan"])


class TargetRequest(BaseModel):
    kind: TargetKind
    id: uuid.UUID


class TaskDoneRequest(BaseModel):
    done: bool = Field(description="Whether the task is finished.")


@router.get("/gap-plans/cost-estimate")
async def cost_estimate(
    kind: Annotated[TargetKind, Query()],
    id: Annotated[uuid.UUID, Query()],
    user: CurrentUser,
    deps: Deps,
) -> dict[str, object]:
    """Drafting runs on the user's key, so it is priced first."""
    return await deps.gapplan.estimate_cost(user, TargetRef(kind, str(id)))


@router.post("/gap-plans", status_code=202)
async def request_plan(body: TargetRequest, user: CurrentUser, deps: Deps) -> dict[str, object]:
    """Records the plan as drafting and queues it; poll ``GET /gap-plans/{id}``."""
    plan = await deps.gapplan.request(user, TargetRef(body.kind, str(body.id)))
    await enqueue("gapplan.draft", owner_id=str(user), plan_id=str(plan.id))
    return _summary_body(plan)


@router.get("/gap-plans")
async def history(user: CurrentUser, deps: Deps) -> list[dict[str, object]]:
    """Plan history: each Target's latest version, newest first."""
    return [_summary_body(plan) for plan in await deps.gapplan.history(user)]


@router.get("/gap-plans/{plan_id}")
async def get_plan(plan_id: uuid.UUID, user: CurrentUser, deps: Deps) -> dict[str, object]:
    return _plan_body(await deps.gapplan.get(user, plan_id))


@router.put("/gap-plan-tasks/{task_id}", status_code=204)
async def set_task_done(
    task_id: uuid.UUID, body: TaskDoneRequest, user: CurrentUser, deps: Deps
) -> None:
    await deps.gapplan.set_task_done(user, task_id, body.done)


def _summary_body(plan: PlanSummaryView) -> dict[str, object]:
    return {
        "id": str(plan.id),
        "target": {"kind": str(plan.target.kind), "id": plan.target.id},
        "label": plan.label,
        "version": plan.version,
        # drafting -> ready | failed. A failure carries the error's stable code.
        "status": str(plan.status),
        "error": (
            {"code": plan.error_code, "message": plan.error_message} if plan.error_code else None
        ),
        "model_id": plan.model_id,
        "created_at": plan.created_at.isoformat(),
        "drafted_at": plan.drafted_at.isoformat() if plan.drafted_at else None,
        "progress": plan.progress,
    }


def _plan_body(plan: PlanView) -> dict[str, object]:
    snapshot = plan.snapshot
    return {
        **_summary_body(plan.summary),
        "template_version": plan.template_version,
        "snapshot": (
            {
                "title": snapshot.title,
                "company": snapshot.company,
                "role_name": snapshot.role_name,
                "fit": snapshot.fit_score,
                # "role": the Role's requirements; "posting": read from the JD.
                "basis": str(snapshot.basis),
                "requirements": [
                    {"statement": r.statement, "expected_level": r.expected_level}
                    for r in snapshot.requirements
                ],
                "taken_at": snapshot.taken_at.isoformat(),
            }
            if snapshot
            else None
        ),
        "gaps": [
            {
                "key": gap.key,
                "kind": gap.kind,
                "name": gap.name,
                "user_score": gap.user_score,
                "target_score": gap.target_score,
                "lift": gap.lift,
                "why": gap.why,
                "evidence": [
                    {"id": e.id, "reference": e.reference, "fact": e.fact} for e in gap.evidence
                ],
            }
            for gap in plan.gaps
        ],
        "milestones": [
            {
                "id": str(milestone.id),
                "title": milestone.title,
                "window": milestone.window,
                "outcome": milestone.outcome,
                "tasks": [
                    {
                        "id": str(task.id),
                        "text": task.text,
                        "due": task.due,
                        "closes": list(task.closes),
                        "done": task.done,
                        "done_elsewhere": task.done_elsewhere,
                    }
                    for task in milestone.tasks
                ],
            }
            for milestone in plan.milestones
        ],
        "projects": list(plan.projects),
        "stepping_stones": [
            {"role_id": s.role_id, "name": s.name, "fit": s.fit, "openings": s.openings}
            for s in plan.stepping_stones
        ],
        "versions": [_summary_body(version) for version in plan.versions],
    }
