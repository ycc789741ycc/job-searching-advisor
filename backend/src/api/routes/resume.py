"""Resume Advisor HTTP surface.

Routes live under ``/tailored-resumes``: ``/resumes`` is the profile's, for
uploaded résumé files. The revision chat is the one streamed route — Server-Sent
Events over a POST, since it carries the current draft and a bearer token that
``EventSource`` cannot send.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from advisor.resume import (
    ExportView,
    Options,
    ResumeSummaryView,
    ResumeView,
    RevisionDone,
    RevisionFailed,
    RevisionText,
    Template,
    VersionView,
)
from advisor.target import TargetKind, TargetRef
from api.dependencies import CurrentUser, Deps
from wiring.queue import enqueue

router = APIRouter(tags=["resume"])


class OptionsBody(BaseModel):
    metrics: bool = True
    reorder: bool = True
    trim: bool = False


class ResumeRequest(BaseModel):
    kind: TargetKind
    id: uuid.UUID
    template: Template = Template.WARM
    options: OptionsBody = Field(default_factory=OptionsBody)


class SettingsRequest(BaseModel):
    template: Template
    options: OptionsBody


class VersionRequest(BaseModel):
    content: dict[str, Any]
    label: str | None = Field(default=None, max_length=200)


class RevisionRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    # The draft as the user sees it now, saved or not.
    content: dict[str, Any]


class ExportRequest(BaseModel):
    version: int = Field(ge=1)


@router.get("/tailored-resumes/cost-estimate")
async def cost_estimate(
    kind: Annotated[TargetKind, Query()],
    id: Annotated[uuid.UUID, Query()],
    user: CurrentUser,
    deps: Deps,
) -> dict[str, object]:
    """Writing runs on the user's key, so it is priced first."""
    return await deps.resume.estimate_cost(user, TargetRef(kind, str(id)))


@router.post("/tailored-resumes", status_code=202)
async def write_resume(body: ResumeRequest, user: CurrentUser, deps: Deps) -> dict[str, object]:
    """Records the résumé as drafting and queues it; poll ``GET /tailored-resumes/{id}``."""
    resume = await deps.resume.request(
        user,
        TargetRef(body.kind, str(body.id)),
        template=body.template,
        options=Options(**body.options.model_dump()),
    )
    await enqueue("resume.generate", owner_id=str(user), resume_id=str(resume.id))
    return _summary_body(resume)


@router.get("/tailored-resumes")
async def saved(user: CurrentUser, deps: Deps) -> list[dict[str, object]]:
    """Saved résumés, most recently changed first."""
    return [_summary_body(r) for r in await deps.resume.saved(user)]


@router.get("/tailored-resumes/{resume_id}")
async def get_resume(
    resume_id: uuid.UUID,
    user: CurrentUser,
    deps: Deps,
    version: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, object]:
    return _resume_body(await deps.resume.get(user, resume_id, number=version))


@router.put("/tailored-resumes/{resume_id}/settings", status_code=204)
async def update_settings(
    resume_id: uuid.UUID, body: SettingsRequest, user: CurrentUser, deps: Deps
) -> None:
    await deps.resume.update_settings(
        user,
        resume_id,
        template=body.template,
        options=Options(**body.options.model_dump()),
    )


@router.post("/tailored-resumes/{resume_id}/versions", status_code=201)
async def save_version(
    resume_id: uuid.UUID, body: VersionRequest, user: CurrentUser, deps: Deps
) -> dict[str, object]:
    version = await deps.resume.save_version(
        user, resume_id, content=body.content, label=body.label
    )
    return _version_body(version)


@router.post("/tailored-resumes/{resume_id}/revisions")
async def revise(
    resume_id: uuid.UUID, body: RevisionRequest, user: CurrentUser, deps: Deps
) -> EventSourceResponse:
    """The revision chat. Events: ``text`` as prose arrives, then exactly one of
    ``proposal`` (applied only on request) or ``error`` ({code, message})."""

    async def events() -> AsyncIterator[dict[str, str]]:
        async for event in deps.resume.revise(
            user, resume_id, request=body.message, content=body.content
        ):
            if isinstance(event, RevisionText):
                yield {"event": "text", "data": json.dumps({"text": event.text})}
            elif isinstance(event, RevisionDone):
                yield {
                    "event": "proposal",
                    "data": json.dumps(
                        {
                            "revision_id": str(event.revision_id),
                            "reply": event.reply,
                            "proposal": event.proposal.to_dict() if event.proposal else None,
                        }
                    ),
                }
            elif isinstance(event, RevisionFailed):
                yield {
                    "event": "error",
                    "data": json.dumps({"code": event.code, "message": event.message}),
                }

    return EventSourceResponse(events())


@router.post("/tailored-resumes/{resume_id}/revisions/{revision_id}/apply", status_code=201)
async def apply_revision(
    resume_id: uuid.UUID, revision_id: uuid.UUID, user: CurrentUser, deps: Deps
) -> dict[str, object]:
    """An accepted chat edit becomes a new version."""
    return _version_body(await deps.resume.apply_revision(user, resume_id, revision_id))


@router.post("/tailored-resumes/{resume_id}/exports", status_code=202)
async def request_export(
    resume_id: uuid.UUID, body: ExportRequest, user: CurrentUser, deps: Deps
) -> dict[str, object]:
    """Renders on the worker's ``docs`` queue; poll ``GET /resume-exports/{id}``."""
    export = await deps.resume.request_export(user, resume_id, number=body.version)
    await enqueue("resume.export", owner_id=str(user), export_id=str(export.id))
    return _export_body(export)


@router.get("/resume-exports/{export_id}")
async def get_export(export_id: uuid.UUID, user: CurrentUser, deps: Deps) -> dict[str, object]:
    return _export_body(await deps.resume.get_export(user, export_id))


def _summary_body(resume: ResumeSummaryView) -> dict[str, object]:
    return {
        "id": str(resume.id),
        "target": {"kind": str(resume.target.kind), "id": resume.target.id},
        "label": resume.label,
        # drafting -> ready | failed. A failure carries the error's stable code.
        "status": resume.status,
        "error": (
            {"code": resume.error_code, "message": resume.error_message}
            if resume.error_code
            else None
        ),
        "latest_version": resume.latest_version,
        "created_at": resume.created_at.isoformat(),
        "updated_at": resume.updated_at.isoformat(),
    }


def _version_body(version: VersionView) -> dict[str, object]:
    return {
        "id": str(version.id),
        "number": version.number,
        "label": version.label,
        # generated | manual | chat
        "source": str(version.source),
        "model_id": version.model_id,
        "created_at": version.created_at.isoformat(),
    }


def _resume_body(resume: ResumeView) -> dict[str, object]:
    snapshot = resume.snapshot
    return {
        **_summary_body(resume.summary),
        "template": str(resume.template),
        "options": {
            "metrics": resume.options.metrics,
            "reorder": resume.options.reorder,
            "trim": resume.options.trim,
        },
        "snapshot": (
            {
                "title": snapshot.title,
                "company": snapshot.company,
                "role_name": snapshot.role_name,
                "fit": snapshot.fit_score,
                "basis": str(snapshot.basis),
            }
            if snapshot
            else None
        ),
        "coverage": [
            {
                "requirement": c.requirement,
                # covered | partial | gap
                "verdict": c.verdict,
                "evidence": [
                    {"id": e.id, "reference": e.reference, "fact": e.fact} for e in c.evidence
                ],
            }
            for c in resume.coverage
        ],
        "version": _version_body(resume.version) if resume.version else None,
        "content": resume.content.to_dict() if resume.content else None,
        # Cited evidence, by id, for the grey note under each line.
        "evidence": {
            key: {"reference": note.reference, "fact": note.fact}
            for key, note in resume.evidence.items()
        },
        "versions": [_version_body(v) for v in resume.versions],
        "revisions": [
            {
                "id": str(r.id),
                "request": r.request,
                "reply": r.reply,
                "has_proposal": r.has_proposal,
                "applied_version_id": str(r.applied_version_id) if r.applied_version_id else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in resume.revisions
        ],
    }


def _export_body(export: ExportView) -> dict[str, object]:
    return {
        "id": str(export.id),
        "version_id": str(export.version_id),
        "template": str(export.template),
        # rendering -> ready | failed
        "status": export.status,
        "error": (
            {"code": export.error_code, "message": export.error_message}
            if export.error_code
            else None
        ),
        # Short-lived and signed; the file itself is never public.
        "download_url": export.download_url,
    }
