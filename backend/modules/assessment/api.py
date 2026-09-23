"""Assessment HTTP surface: the radar, the follow-up questions and the fits."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.dependencies import CurrentUser, Deps
from app.queue import enqueue
from domain.assessment import DEFAULT_MATCHES, MAX_MATCHES, MIN_MATCHES

router = APIRouter(tags=["assessment"])


class AnswerRequest(BaseModel):
    answer: str = Field(min_length=1)


@router.get("/assessments/cost-estimate")
async def cost_estimate(user: CurrentUser, deps: Deps) -> dict[str, object]:
    """The first analysis is priced and confirmed before it runs."""
    return await deps.assessment.estimate_cost(user)


@router.post("/assessments", status_code=202)
async def run_assessment(user: CurrentUser, deps: Deps) -> dict[str, str]:
    await enqueue("assessment.run", owner_id=str(user))
    return {"status": "queued"}


@router.get("/assessments/latest")
async def latest(user: CurrentUser, deps: Deps) -> dict[str, object] | None:
    assessment = await deps.assessment.latest(user)
    return _assessment_body(assessment) if assessment is not None else None


@router.get("/assessments")
async def history(user: CurrentUser, deps: Deps) -> list[dict[str, object]]:
    return [_assessment_body(a) for a in await deps.assessment.history(user)]


@router.get("/questions")
async def questions(user: CurrentUser, deps: Deps) -> list[dict[str, object]]:
    return [
        {
            "id": str(q.id),
            "dimension_key": q.dimension_key,
            "text": q.text,
            # Every question says what it is for and which dimension it moves.
            "why": q.why,
            "options": list(q.options),
            "answer": q.answer,
        }
        for q in await deps.assessment.questions(user)
    ]


@router.post("/questions/{question_id}/answer", status_code=202)
async def answer(
    question_id: uuid.UUID, body: AnswerRequest, user: CurrentUser, deps: Deps
) -> dict[str, str]:
    """An answer becomes self-reported Evidence, then the analysis re-runs."""
    await deps.assessment.answer(user, question_id, body.answer)
    await enqueue("assessment.run", owner_id=str(user))
    return {"status": "queued"}


@router.get("/fits")
async def fits(user: CurrentUser, deps: Deps) -> list[dict[str, object]]:
    """Bubble sizes. Fit belongs to the User x Role pair, never to the role."""
    return [
        {
            "role_id": str(f.role_id) if f.role_id else None,
            "private_posting_id": str(f.private_posting_id) if f.private_posting_id else None,
            "score": f.score,
            "reasoning": f.reasoning,
            "gaps": list(f.gaps),
            # Requirements with no matching dimension: no evidence at all,
            # which is different from a low score.
            "uncovered": list(f.uncovered),
            "model_id": f.model_id,
            "computed_at": f.created_at.isoformat(),
        }
        for f in await deps.assessment.fits(user)
    ]


@router.get("/matched-postings")
async def matched_postings(
    user: CurrentUser,
    deps: Deps,
    limit: Annotated[int, Query(ge=MIN_MATCHES, le=MAX_MATCHES)] = DEFAULT_MATCHES,
) -> list[dict[str, object]]:
    """The best openings inside the user's roles, for the role map's "Top
    matched" list. Ranked by the role's fit; no AI runs to produce it."""
    return [
        {
            "posting_id": str(m.posting_id),
            "role_id": str(m.role_id),
            "role_name": m.role_name,
            "title": m.title,
            "company_name": m.company_name,
            "location": m.location,
            "url": m.url,
            "salary": (
                {
                    "min": m.salary.min_amount,
                    "max": m.salary.max_amount,
                    "currency": m.salary.currency,
                }
                if m.salary
                else None
            ),
            # The role's fit: a posting's own requirements do not move it yet.
            "fit": m.fit,
            "fit_basis": "role",
            "subscription_id": str(m.subscription_id) if m.subscription_id else None,
            "source_kind": m.source_kind,
        }
        for m in await deps.assessment.matched_postings(user, limit=limit)
    ]


@router.post("/fits/compute", status_code=202)
async def compute_fits(user: CurrentUser, deps: Deps) -> dict[str, str]:
    await enqueue("assessment.compute_fits", owner_id=str(user))
    return {"status": "queued"}


def _assessment_body(assessment: object) -> dict[str, object]:
    return {
        "id": str(assessment.id),  # type: ignore[attr-defined]
        "profile_version": assessment.profile_version,  # type: ignore[attr-defined]
        "model_id": assessment.model_id,  # type: ignore[attr-defined]
        "template_version": assessment.template_version,  # type: ignore[attr-defined]
        "created_at": assessment.created_at.isoformat(),  # type: ignore[attr-defined]
        "dimensions": [
            {
                "key": d.key,
                "name": d.name,
                "short_name": d.short_name,
                "score": d.score,
                "confidence": d.confidence,
                "read": d.read,
                "evidence_ids": list(d.evidence_ids),
            }
            for d in assessment.dimensions  # type: ignore[attr-defined]
        ],
    }


__all__ = ["router"]
