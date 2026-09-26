"""Gap plans: closing the distance to one Target (domain decision 16).

A plan is requested in the api and drafted by a worker job on the user's key.
The row exists from the moment it is requested, with a status, so the page can
poll it and say plainly when drafting failed and why (ADR 0006).

Plans are never overwritten. Regenerating adds the next version for the same
Target and carries finished tasks into it; the history is every Target's latest
version, newest first.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from advisor.assessment import AssessmentService
from advisor.gapplan.domain import (
    MAX_MILESTONES,
    MAX_PROJECTS,
    MAX_TASKS_PER_MILESTONE,
    SHOWN_GAPS,
    DraftMilestone,
    DraftProject,
    DraftTask,
    GapReading,
    PlanError,
    PlanStatus,
    RoleOption,
    assert_draft_valid,
    carried_done,
    progress,
    stepping_stones,
)
from advisor.gapplan.infra.models import GapPlan, Milestone, Task
from advisor.profile import CitationError, ProfileService, assert_citations_exist
from advisor.rolemap import RoleMapService
from advisor.target import (
    DimensionGap,
    TargetKind,
    TargetRef,
    TargetService,
    TargetSnapshot,
    requirements_block,
)
from kernel.ai_gateway import AiGateway
from kernel.ai_gateway import load as load_template
from kernel.db import Database
from kernel.db.base import utcnow
from kernel.errors import (
    DomainError,
    EvidenceNotOwnedError,
    NotFoundError,
    PlanInvalidError,
    TargetUnusableError,
)
from kernel.logging import get_logger
from kernel.outbox import EventName, emit

__all__ = [
    "EvidenceCite",
    "GapPlanService",
    "GapView",
    "MilestoneView",
    "PlanStatus",
    "PlanSummaryView",
    "PlanView",
    "SteppingStoneView",
    "TaskView",
]

log = get_logger(__name__)

_TEMPLATE = ("gap_plan", "v1")
_UNTRUSTED = frozenset({"requirements", "evidence", "dimensions"})


# --- AI output schema ------------------------------------------------------


class _Gap(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    why: str = Field(min_length=1, max_length=1200)
    evidence_ids: list[str] = Field(default_factory=list, max_length=12)


class _Task(BaseModel):
    text: str = Field(min_length=1, max_length=400)
    due: str = Field(min_length=1, max_length=32)
    closes: list[str] = Field(min_length=1, max_length=6)


class _Milestone(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    window: str = Field(min_length=1, max_length=64)
    outcome: str = Field(min_length=1, max_length=600)
    tasks: list[_Task] = Field(min_length=1, max_length=MAX_TASKS_PER_MILESTONE)


class _Project(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    note: str = Field(min_length=1, max_length=600)
    closes: list[str] = Field(min_length=1, max_length=6)


class _Plan(BaseModel):
    gaps: list[_Gap] = Field(min_length=1, max_length=SHOWN_GAPS)
    milestones: list[_Milestone] = Field(min_length=1, max_length=MAX_MILESTONES)
    projects: list[_Project] = Field(default_factory=list, max_length=MAX_PROJECTS)


# --- views -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvidenceCite:
    id: str
    reference: str
    fact: str


@dataclass(frozen=True, slots=True)
class GapView:
    key: str
    # "dimension": a skill scored below the bar; "uncovered": no evidence at all.
    kind: str
    name: str
    user_score: int | None
    target_score: int | None
    lift: int
    why: str
    evidence: tuple[EvidenceCite, ...]


@dataclass(frozen=True, slots=True)
class TaskView:
    id: uuid.UUID
    text: str
    due: str
    closes: tuple[str, ...]
    done: bool
    # Not ticked here, but a matching task closing the same gap is done in
    # another plan — it counts here too.
    done_elsewhere: bool


@dataclass(frozen=True, slots=True)
class MilestoneView:
    id: uuid.UUID
    title: str
    window: str
    outcome: str
    tasks: tuple[TaskView, ...]


@dataclass(frozen=True, slots=True)
class SteppingStoneView:
    role_id: str
    name: str
    fit: int
    openings: int


@dataclass(frozen=True, slots=True)
class PlanSummaryView:
    id: uuid.UUID
    target: TargetRef
    label: str
    version: int
    status: PlanStatus
    error_code: str | None
    error_message: str | None
    model_id: str | None
    created_at: datetime
    drafted_at: datetime | None
    progress: int


@dataclass(frozen=True, slots=True)
class PlanView:
    summary: PlanSummaryView
    snapshot: TargetSnapshot | None
    gaps: tuple[GapView, ...]
    milestones: tuple[MilestoneView, ...]
    projects: tuple[dict[str, Any], ...]
    stepping_stones: tuple[SteppingStoneView, ...]
    # Every version for this Target, newest first.
    versions: tuple[PlanSummaryView, ...]
    template_version: str | None


# --- service ---------------------------------------------------------------


class GapPlanService:
    def __init__(
        self,
        database: Database,
        *,
        target: TargetService,
        profile: ProfileService,
        assessment: AssessmentService,
        rolemap: RoleMapService,
        gateway: AiGateway,
    ) -> None:
        self._db = database
        self._target = target
        self._profile = profile
        self._assessment = assessment
        self._rolemap = rolemap
        self._gateway = gateway

    async def estimate_cost(self, owner_id: uuid.UUID, ref: TargetRef) -> dict[str, Any]:
        """Priced before anything is spent. A pasted JD not yet scored adds that."""
        preview = await self._target.preview(owner_id, ref)
        inputs = await self._inputs(
            owner_id,
            label=preview.label,
            requirements=preview.requirements_text,
            snapshot=preview.snapshot,
        )
        estimate = await self._gateway.estimate(
            owner_id,
            task="gapplan.draft",
            template=load_template(*_TEMPLATE),
            inputs=inputs,
            untrusted=_UNTRUSTED,
        )
        return {
            "cost_usd": str(estimate.cost_usd + preview.pending_cost_usd),
            "model_id": estimate.model_id,
            "input_tokens": estimate.input_tokens,
            "rate_is_published": estimate.rate_is_published,
            "includes_scoring": preview.pending_cost_usd > Decimal(0),
        }

    async def request(self, owner_id: uuid.UUID, ref: TargetRef) -> PlanSummaryView:
        """Record the plan as drafting; the caller queues ``draft``.

        The Target is resolved here, so a Target that cannot be planned for is
        refused now rather than failing in the background.
        """
        preview = await self._target.preview(owner_id, ref)
        async with self._db.for_user(owner_id) as session:
            previous = await session.execute(
                select(GapPlan.version).where(GapPlan.owner_id == owner_id, *_target_filter(ref))
            )
            version = max(previous.scalars(), default=0) + 1
            plan = GapPlan(
                owner_id=owner_id,
                target_kind=str(ref.kind),
                target_label=preview.label[:400],
                version=version,
                status=str(PlanStatus.DRAFTING),
                created_at=utcnow(),
                **_target_columns(ref),
            )
            session.add(plan)
            await session.flush()
            return _summary(plan, progress_percent=0)

    async def draft(self, owner_id: uuid.UUID, plan_id: uuid.UUID) -> None:
        """The worker job. Any expected failure is recorded on the plan, with
        its stable code, and not retried: a retry would spend the key again."""
        async with self._db.for_user(owner_id) as session:
            plan = await session.get(GapPlan, plan_id)
            if plan is None or plan.owner_id != owner_id:
                raise NotFoundError("plan not found", plan_id=str(plan_id))
            if plan.status != str(PlanStatus.DRAFTING):
                return
            ref = _ref_of(plan)

        try:
            await self._draft(owner_id, plan_id, ref)
        except DomainError as exc:
            log.warning("gapplan.draft_failed", plan_id=str(plan_id), code=str(exc.code))
            await self._fail(owner_id, plan_id, code=str(exc.code), message=exc.message)
        except Exception:
            await self._fail(
                owner_id,
                plan_id,
                code="internal",
                message="Drafting stopped unexpectedly. Try again in a moment.",
            )
            raise

    async def get(self, owner_id: uuid.UUID, plan_id: uuid.UUID) -> PlanView:
        async with self._db.for_user(owner_id) as session:
            plan = await session.get(GapPlan, plan_id)
            if plan is None or plan.owner_id != owner_id:
                raise NotFoundError("plan not found", plan_id=str(plan_id))
            all_plans = list(
                (
                    await session.execute(
                        select(GapPlan)
                        .where(GapPlan.owner_id == owner_id)
                        .order_by(GapPlan.created_at.desc())
                    )
                ).scalars()
            )
            milestones = list(
                (
                    await session.execute(
                        select(Milestone)
                        .where(Milestone.plan_id == plan_id)
                        .order_by(Milestone.position)
                    )
                ).scalars()
            )
            tasks = await _tasks_by_plan(session, owner_id)

        done_elsewhere = _done_tasks(tasks, excluding=plan_id)
        own = tasks.get(plan_id, [])
        counted = carried_done([(t.text, t.closes) for t in own], done_elsewhere)
        task_views = {
            task.id: TaskView(
                id=task.id,
                text=task.text,
                due=task.due,
                closes=tuple(task.closes),
                done=task.done_at is not None,
                done_elsewhere=task.done_at is None and index in counted,
            )
            for index, task in enumerate(own)
        }
        progress_by_plan = _progress_by_plan(tasks)
        same_target = [p for p in all_plans if _ref_of(p) == _ref_of(plan)]

        return PlanView(
            summary=_summary(plan, progress_percent=progress_by_plan.get(plan.id, 0)),
            snapshot=TargetSnapshot.from_dict(plan.snapshot) if plan.snapshot else None,
            gaps=tuple(_gap_view(g) for g in plan.gaps),
            milestones=tuple(
                MilestoneView(
                    id=m.id,
                    title=m.title,
                    window=m.time_window,
                    outcome=m.outcome,
                    tasks=tuple(
                        task_views[t.id]
                        for t in sorted(own, key=lambda t: t.position)
                        if t.milestone_id == m.id
                    ),
                )
                for m in milestones
            ),
            projects=tuple(plan.projects),
            stepping_stones=tuple(SteppingStoneView(**s) for s in plan.stepping_stones),
            versions=tuple(
                _summary(p, progress_percent=progress_by_plan.get(p.id, 0)) for p in same_target
            ),
            template_version=plan.template_version,
        )

    async def history(self, owner_id: uuid.UUID) -> list[PlanSummaryView]:
        """Each Target's latest version, newest first. Every plan is kept."""
        async with self._db.for_user(owner_id) as session:
            plans = list(
                (
                    await session.execute(
                        select(GapPlan)
                        .where(GapPlan.owner_id == owner_id)
                        .order_by(GapPlan.created_at.desc())
                    )
                ).scalars()
            )
            tasks = await _tasks_by_plan(session, owner_id)
        progress_by_plan = _progress_by_plan(tasks)
        seen: set[TargetRef] = set()
        latest: list[PlanSummaryView] = []
        for plan in plans:
            ref = _ref_of(plan)
            if ref in seen:
                continue
            seen.add(ref)
            latest.append(_summary(plan, progress_percent=progress_by_plan.get(plan.id, 0)))
        return latest

    async def set_task_done(self, owner_id: uuid.UUID, task_id: uuid.UUID, done: bool) -> None:
        async with self._db.for_user(owner_id) as session:
            task = await session.get(Task, task_id)
            if task is None or task.owner_id != owner_id:
                raise NotFoundError("task not found", task_id=str(task_id))
            task.done_at = (task.done_at or utcnow()) if done else None

    # -- internals ----------------------------------------------------------

    async def _draft(self, owner_id: uuid.UUID, plan_id: uuid.UUID, ref: TargetRef) -> None:
        snapshot = await self._target.snapshot(owner_id, ref)
        shown = snapshot.open_gaps[:SHOWN_GAPS]
        if not shown:
            raise TargetUnusableError(
                f"you already clear everything {snapshot.label} asks for; there is nothing to plan",
            )

        result = await self._gateway.run(
            owner_id,
            task="gapplan.draft",
            template=load_template(*_TEMPLATE),
            inputs=await self._inputs(
                owner_id,
                label=snapshot.label,
                requirements=requirements_block(snapshot),
                snapshot=snapshot,
            ),
            output_schema=_Plan,
            untrusted=_UNTRUSTED,
        )
        draft = result.value
        readings = [GapReading(g.key, g.why, tuple(g.evidence_ids)) for g in draft.gaps]
        milestones = [
            DraftMilestone(
                title=m.title,
                window=m.window,
                outcome=m.outcome,
                tasks=tuple(DraftTask(t.text, t.due, tuple(t.closes)) for t in m.tasks),
            )
            for m in draft.milestones
        ]
        projects = [DraftProject(p.name, p.note, tuple(p.closes)) for p in draft.projects]
        shown_keys = [gap.key for gap in shown]
        try:
            assert_draft_valid(
                readings=readings,
                milestones=milestones,
                projects=projects,
                shown_keys=shown_keys,
                dimension_keys=[g.key for g in shown if isinstance(g, DimensionGap)],
            )
        except PlanError as exc:
            raise PlanInvalidError(f"the drafted plan was rejected: {exc}") from exc

        profile = await self._profile.snapshot(owner_id)
        evidence = {str(e.id): e for e in profile.evidence}
        cited = {i for reading in readings for i in reading.evidence_ids}
        try:
            assert_citations_exist(cited, set(evidence))
        except CitationError as exc:
            # An invented citation is how a fabricated claim gets in.
            raise EvidenceNotOwnedError(
                "the plan cited evidence that is not in your profile",
                invented=sorted(exc.invented),
            ) from exc

        reading_by_key = {r.key: r for r in readings}
        gaps = [
            {
                "key": gap.key,
                **(
                    {
                        "kind": "dimension",
                        "name": gap.name,
                        "user_score": gap.user_score,
                        "target_score": gap.target_score,
                    }
                    if isinstance(gap, DimensionGap)
                    else {
                        "kind": "uncovered",
                        "name": gap.statement,
                        "user_score": None,
                        "target_score": None,
                    }
                ),
                "lift": gap.lift,
                "why": reading_by_key[gap.key].why,
                "evidence": [
                    {"id": i, "reference": evidence[i].reference, "fact": evidence[i].fact}
                    for i in reading_by_key[gap.key].evidence_ids
                ],
            }
            for gap in shown
        ]

        stones = await self._stepping_stones(owner_id, snapshot)
        async with self._db.for_user(owner_id) as session:
            plan = await session.get(GapPlan, plan_id)
            if plan is None:
                raise NotFoundError("plan not found", plan_id=str(plan_id))
            previous_done = await self._previous_done(session, owner_id, plan)

            new_tasks: list[Task] = []
            for m_index, milestone in enumerate(milestones):
                row = Milestone(
                    owner_id=owner_id,
                    plan_id=plan_id,
                    position=m_index,
                    title=milestone.title,
                    time_window=milestone.window,
                    outcome=milestone.outcome,
                )
                session.add(row)
                await session.flush()
                for drafted in milestone.tasks:
                    new_tasks.append(
                        Task(
                            owner_id=owner_id,
                            plan_id=plan_id,
                            milestone_id=row.id,
                            position=len(new_tasks),
                            text=drafted.text,
                            due=drafted.due,
                            closes=list(drafted.closes),
                        )
                    )
            # Regenerating rewords tasks; finished work stays finished.
            carried = carried_done([(t.text, t.closes) for t in new_tasks], previous_done)
            now = utcnow()
            for index, task in enumerate(new_tasks):
                if index in carried:
                    task.done_at = now
                session.add(task)

            plan.snapshot = snapshot.to_dict()
            plan.target_label = snapshot.label[:400]
            plan.gaps = gaps
            plan.projects = [
                {"name": p.name, "note": p.note, "closes": list(p.closes)} for p in projects
            ]
            plan.stepping_stones = [
                {"role_id": s.role_id, "name": s.name, "fit": s.fit, "openings": s.openings}
                for s in stones
            ]
            plan.model_id = result.model_id
            plan.template_version = result.template_version
            plan.status = str(PlanStatus.READY)
            plan.drafted_at = now
            await emit(
                session,
                EventName.PLAN_DRAFTED,
                {"plan_id": str(plan_id), "target_kind": str(ref.kind), "version": plan.version},
                owner_id=owner_id,
            )

    async def _inputs(
        self,
        owner_id: uuid.UUID,
        *,
        label: str,
        requirements: str,
        snapshot: TargetSnapshot | None,
    ) -> dict[str, str]:
        profile = await self._profile.snapshot(owner_id)
        assessment = await self._assessment.latest(owner_id)
        if snapshot is None:
            gaps = "(worked out once the job description has been scored)"
        else:
            lines = []
            for gap in snapshot.open_gaps[:SHOWN_GAPS]:
                if isinstance(gap, DimensionGap):
                    lines.append(
                        f"- {gap.key} — {gap.name}: scored {gap.user_score}, the job expects "
                        f"{gap.target_score} (worth {gap.lift} fit points)"
                    )
                else:
                    lines.append(
                        f"- {gap.key} — no evidence at all for: {gap.statement} "
                        f"(worth {gap.lift} fit points)"
                    )
            gaps = "\n".join(lines) or "(none)"
        return {
            "target": label,
            "requirements": requirements,
            "gaps": gaps,
            "dimensions": "\n".join(
                f"- dim:{d.key} {d.name} ({d.score}/100): {d.read}"
                for d in (assessment.dimensions if assessment else ())
            )
            or "(no analysis yet)",
            "evidence": "\n".join(
                f"[{e.id}] ({e.source}) {e.reference}: {e.fact}" for e in profile.evidence
            )
            or "(no evidence)",
        }

    async def _stepping_stones(
        self, owner_id: uuid.UUID, snapshot: TargetSnapshot
    ) -> tuple[RoleOption, ...]:
        fits = {f.role_id: f.score for f in await self._assessment.fits(owner_id) if f.role_id}
        roles = [
            RoleOption(
                role_id=str(role.id),
                name=role.name,
                fit=fits[role.id],
                openings=role.opening_count,
            )
            for role in await self._rolemap.roles(owner_id)
            if role.id in fits
        ]
        return stepping_stones(
            target_role_id=snapshot.role_id, target_fit=snapshot.fit_score, roles=roles
        )

    async def _previous_done(
        self, session: Any, owner_id: uuid.UUID, plan: GapPlan
    ) -> list[tuple[str, list[str]]]:
        """Finished tasks from earlier versions of this plan's Target."""
        earlier = await session.execute(
            select(Task.text, Task.closes)
            .join(GapPlan, Task.plan_id == GapPlan.id)
            .where(
                Task.owner_id == owner_id,
                Task.done_at.is_not(None),
                GapPlan.id != plan.id,
                *_target_filter(_ref_of(plan)),
            )
        )
        return [(text, list(closes)) for text, closes in earlier.all()]

    async def _fail(
        self, owner_id: uuid.UUID, plan_id: uuid.UUID, *, code: str, message: str
    ) -> None:
        async with self._db.for_user(owner_id) as session:
            plan = await session.get(GapPlan, plan_id)
            if plan is not None:
                plan.status = str(PlanStatus.FAILED)
                plan.error_code = code
                plan.error_message = message


# --- helpers ---------------------------------------------------------------


def _target_columns(ref: TargetRef) -> dict[str, uuid.UUID]:
    column = {
        TargetKind.MATCHED_POSTING: "job_posting_id",
        TargetKind.SUBSCRIPTION: "subscription_id",
        TargetKind.PRIVATE_POSTING: "private_posting_id",
    }[ref.kind]
    return {column: uuid.UUID(ref.id)}


def _target_filter(ref: TargetRef) -> list[Any]:
    column, value = next(iter(_target_columns(ref).items()))
    return [GapPlan.target_kind == str(ref.kind), getattr(GapPlan, column) == value]


def _ref_of(plan: GapPlan) -> TargetRef:
    reference = plan.job_posting_id or plan.subscription_id or plan.private_posting_id
    return TargetRef(TargetKind(plan.target_kind), str(reference))


async def _tasks_by_plan(session: Any, owner_id: uuid.UUID) -> dict[uuid.UUID, list[Task]]:
    rows = await session.execute(
        select(Task).where(Task.owner_id == owner_id).order_by(Task.position)
    )
    by_plan: dict[uuid.UUID, list[Task]] = {}
    for task in rows.scalars():
        by_plan.setdefault(task.plan_id, []).append(task)
    return by_plan


def _done_tasks(
    tasks: dict[uuid.UUID, list[Task]], *, excluding: uuid.UUID | None = None
) -> list[tuple[str, list[str]]]:
    return [
        (task.text, list(task.closes))
        for plan_id, plan_tasks in tasks.items()
        if plan_id != excluding
        for task in plan_tasks
        if task.done_at is not None
    ]


def _progress_by_plan(tasks: dict[uuid.UUID, list[Task]]) -> dict[uuid.UUID, int]:
    """Done here, or done as a matching task in another plan."""
    result: dict[uuid.UUID, int] = {}
    for plan_id, plan_tasks in tasks.items():
        elsewhere = carried_done(
            [(t.text, t.closes) for t in plan_tasks], _done_tasks(tasks, excluding=plan_id)
        )
        result[plan_id] = progress(
            [t.done_at is not None or i in elsewhere for i, t in enumerate(plan_tasks)]
        )
    return result


def _summary(plan: GapPlan, *, progress_percent: int) -> PlanSummaryView:
    return PlanSummaryView(
        id=plan.id,
        target=_ref_of(plan),
        label=plan.target_label,
        version=plan.version,
        status=PlanStatus(plan.status),
        error_code=plan.error_code,
        error_message=plan.error_message,
        model_id=plan.model_id,
        created_at=plan.created_at,
        drafted_at=plan.drafted_at,
        progress=progress_percent,
    )


def _gap_view(data: dict[str, Any]) -> GapView:
    return GapView(
        key=data["key"],
        kind=data["kind"],
        name=data["name"],
        user_score=data.get("user_score"),
        target_score=data.get("target_score"),
        lift=data["lift"],
        why=data["why"],
        evidence=tuple(EvidenceCite(**e) for e in data.get("evidence", [])),
    )
