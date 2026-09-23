"""The Resume Advisor: one résumé per Target, written from cited evidence.

* A résumé is requested in the api and its first version written by a worker
  job on the user's key; the row exists from the request with a status the page
  polls (ADR 0006).
* Versions are never overwritten. A manual save, a generated draft and an edit
  applied from the chat each add one.
* The revision chat streams from the api: prose as it arrives, then a proposed
  revision the user applies or ignores (ADR 0007 is about export; the chat is
  ``AiGateway.stream_structured``).
* Export renders a version to PDF on the worker's ``docs`` queue and hands back
  a short-lived signed link.

Every line the model writes must cite Evidence the user owns; a reply that
does not is rejected as a whole. Coverage of the Target's requirements is
computed from scores, not written by the model.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select

from domain.resume import (
    MAX_BULLETS_PER_ROLE,
    MAX_ROLES,
    MAX_SKILLS,
    Coverage,
    Options,
    Origin,
    ResumeContent,
    ResumeError,
    Template,
    VersionSource,
    assert_well_formed,
    assert_written_lines_cited,
    coverage,
    mark_edits,
    settle_revision,
)
from kernel.ai_gateway import AiGateway, StreamResult, StreamText
from kernel.ai_gateway import load as load_template
from kernel.db import Database
from kernel.db.base import utcnow
from kernel.errors import (
    DomainError,
    EvidenceNotOwnedError,
    NotFoundError,
    OutputInvalidError,
    ValidationError,
)
from kernel.logging import get_logger
from kernel.outbox import EventName, emit
from kernel.storage import ObjectStore, object_key
from modules.assessment.public import AssessmentService
from modules.profile.public import CitationError, ProfileService, assert_citations_exist
from modules.resume.infra.models import Export, Resume, ResumeVersion, Revision
from modules.resume.infra.render import render_html, render_pdf
from modules.target.public import (
    TargetKind,
    TargetRef,
    TargetService,
    TargetSnapshot,
    requirements_block,
)

__all__ = [
    "CoverageView",
    "ExportView",
    "Options",
    "ResumeService",
    "ResumeSummaryView",
    "ResumeView",
    "RevisionDone",
    "RevisionFailed",
    "RevisionText",
    "RevisionView",
    "Template",
    "VersionView",
]

log = get_logger(__name__)

_WRITE = ("resume_write", "v1")
_REVISE = ("resume_revise", "v1")
_MARKER = "<<<PROPOSAL>>>"
# The chat sees this many earlier exchanges, newest last.
_CONVERSATION_TURNS = 6
# Everything the chat reads that a person or a posting wrote.
_REVISE_UNTRUSTED = frozenset({"requirements", "resume", "conversation", "request", "evidence"})


# --- AI output schemas -----------------------------------------------------


class _Bullet(BaseModel):
    text: str = Field(min_length=1, max_length=600)
    evidence_ids: list[str] = Field(default_factory=list, max_length=8)
    answers: str | None = Field(default=None, max_length=400)
    origin: str | None = None


class _Position(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    org: str = Field(default="", max_length=200)
    when: str = Field(default="", max_length=64)
    bullets: list[_Bullet] = Field(default_factory=list, max_length=MAX_BULLETS_PER_ROLE)


class _Resume(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    headline: str = Field(default="", max_length=200)
    contact: str = Field(default="", max_length=300)
    summary: str = Field(default="", max_length=1200)
    experience: list[_Position] = Field(default_factory=list, max_length=MAX_ROLES)
    skills: list[str] = Field(default_factory=list, max_length=MAX_SKILLS)


class _Proposal(BaseModel):
    changed: bool
    resume: _Resume | None = None


# --- views -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvidenceNote:
    id: str
    reference: str
    fact: str


@dataclass(frozen=True, slots=True)
class CoverageView:
    requirement: str
    verdict: str
    dimension_key: str | None
    evidence: tuple[EvidenceNote, ...]


@dataclass(frozen=True, slots=True)
class VersionView:
    id: uuid.UUID
    number: int
    label: str
    source: VersionSource
    model_id: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RevisionView:
    id: uuid.UUID
    request: str
    reply: str
    has_proposal: bool
    applied_version_id: uuid.UUID | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ResumeSummaryView:
    id: uuid.UUID
    target: TargetRef
    label: str
    status: str
    error_code: str | None
    error_message: str | None
    latest_version: int | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ResumeView:
    summary: ResumeSummaryView
    snapshot: TargetSnapshot | None
    coverage: tuple[CoverageView, ...]
    template: Template
    options: Options
    version: VersionView | None
    content: ResumeContent | None
    # Evidence cited anywhere in this version, for the grey notes.
    evidence: dict[str, EvidenceNote]
    versions: tuple[VersionView, ...]
    revisions: tuple[RevisionView, ...]


@dataclass(frozen=True, slots=True)
class ExportView:
    id: uuid.UUID
    version_id: uuid.UUID
    template: Template
    status: str
    error_code: str | None
    error_message: str | None
    download_url: str | None


@dataclass(frozen=True, slots=True)
class RevisionText:
    text: str


@dataclass(frozen=True, slots=True)
class RevisionDone:
    revision_id: uuid.UUID
    reply: str
    # The whole proposed résumé, settled and validated; None for advice only.
    proposal: ResumeContent | None


@dataclass(frozen=True, slots=True)
class RevisionFailed:
    code: str
    message: str


RevisionEvent = RevisionText | RevisionDone | RevisionFailed


# --- service ---------------------------------------------------------------


class ResumeService:
    def __init__(
        self,
        database: Database,
        *,
        target: TargetService,
        profile: ProfileService,
        assessment: AssessmentService,
        gateway: AiGateway,
        object_store: ObjectStore,
    ) -> None:
        self._db = database
        self._target = target
        self._profile = profile
        self._assessment = assessment
        self._gateway = gateway
        self._store = object_store

    # -- writing ------------------------------------------------------------

    async def estimate_cost(self, owner_id: uuid.UUID, ref: TargetRef) -> dict[str, Any]:
        """Priced before anything is spent. A pasted JD not yet scored adds that."""
        preview = await self._target.preview(owner_id, ref)
        estimate = await self._gateway.estimate(
            owner_id,
            task="resume.generate",
            template=load_template(*_WRITE),
            inputs=await self._write_inputs(
                owner_id,
                label=preview.label,
                requirements=preview.requirements_text,
                coverage_rows=(),
                options=Options(),
                base_resume="(read when writing)",
            ),
            untrusted=frozenset({"requirements", "evidence", "timeline", "base_resume"}),
        )
        return {
            "cost_usd": str(estimate.cost_usd + preview.pending_cost_usd),
            "model_id": estimate.model_id,
            "input_tokens": estimate.input_tokens,
            "rate_is_published": estimate.rate_is_published,
            "includes_scoring": preview.pending_cost_usd > Decimal(0),
        }

    async def request(
        self, owner_id: uuid.UUID, ref: TargetRef, *, template: Template, options: Options
    ) -> ResumeSummaryView:
        """Record the résumé as drafting; the caller queues ``generate``."""
        preview = await self._target.preview(owner_id, ref)
        now = utcnow()
        async with self._db.for_user(owner_id) as session:
            resume = Resume(
                owner_id=owner_id,
                target_kind=str(ref.kind),
                target_label=preview.label[:400],
                template=str(template),
                options=_options_dict(options),
                status="drafting",
                created_at=now,
                updated_at=now,
                **_target_columns(ref),
            )
            session.add(resume)
            await session.flush()
            return _summary(resume, latest_version=None)

    async def generate(self, owner_id: uuid.UUID, resume_id: uuid.UUID) -> None:
        """The worker job. An expected failure is recorded on the résumé, with
        its stable code, and not retried on the user's key."""
        async with self._db.for_user(owner_id) as session:
            resume = await session.get(Resume, resume_id)
            if resume is None or resume.owner_id != owner_id:
                raise NotFoundError("résumé not found", resume_id=str(resume_id))
            if resume.status != "drafting":
                return
            ref = _ref_of(resume)
            options = _options_of(resume.options)

        try:
            await self._generate(owner_id, resume_id, ref, options)
        except DomainError as exc:
            log.warning("resume.generate_failed", resume_id=str(resume_id), code=str(exc.code))
            await self._fail(owner_id, resume_id, code=str(exc.code), message=exc.message)
        except Exception:
            await self._fail(
                owner_id,
                resume_id,
                code="internal",
                message="Writing stopped unexpectedly. Try again in a moment.",
            )
            raise

    # -- reading ------------------------------------------------------------

    async def saved(self, owner_id: uuid.UUID) -> list[ResumeSummaryView]:
        """Saved résumés, most recently changed first."""
        async with self._db.for_user(owner_id) as session:
            rows = await session.execute(
                select(Resume).where(Resume.owner_id == owner_id).order_by(Resume.updated_at.desc())
            )
            resumes = list(rows.scalars())
            latest = await session.execute(
                select(ResumeVersion.resume_id, func.max(ResumeVersion.number))
                .where(ResumeVersion.owner_id == owner_id)
                .group_by(ResumeVersion.resume_id)
            )
            numbers = dict(latest.tuples().all())
        return [_summary(r, latest_version=numbers.get(r.id)) for r in resumes]

    async def get(
        self, owner_id: uuid.UUID, resume_id: uuid.UUID, *, number: int | None = None
    ) -> ResumeView:
        async with self._db.for_user(owner_id) as session:
            resume = await _owned(session, owner_id, resume_id)
            versions = list(
                (
                    await session.execute(
                        select(ResumeVersion)
                        .where(ResumeVersion.resume_id == resume_id)
                        .order_by(ResumeVersion.number.desc())
                    )
                ).scalars()
            )
            revisions = list(
                (
                    await session.execute(
                        select(Revision)
                        .where(Revision.resume_id == resume_id)
                        .order_by(Revision.created_at)
                    )
                ).scalars()
            )

        chosen = (
            next((v for v in versions if v.number == number), None)
            if number is not None
            else (versions[0] if versions else None)
        )
        if number is not None and chosen is None:
            raise NotFoundError("version not found", number=number)
        content = ResumeContent.from_dict(chosen.content) if chosen else None
        notes = await self._notes(owner_id, content.cited() if content else set())
        return ResumeView(
            summary=_summary(resume, latest_version=versions[0].number if versions else None),
            snapshot=TargetSnapshot.from_dict(resume.snapshot) if resume.snapshot else None,
            coverage=tuple(_coverage_view(c) for c in resume.coverage),
            template=Template(resume.template),
            options=_options_of(resume.options),
            version=_version_view(chosen) if chosen else None,
            content=content,
            evidence=notes,
            versions=tuple(_version_view(v) for v in versions),
            revisions=tuple(_revision_view(r) for r in revisions),
        )

    # -- editing ------------------------------------------------------------

    async def update_settings(
        self,
        owner_id: uuid.UUID,
        resume_id: uuid.UUID,
        *,
        template: Template,
        options: Options,
    ) -> None:
        async with self._db.for_user(owner_id) as session:
            resume = await _owned(session, owner_id, resume_id)
            resume.template = str(template)
            resume.options = _options_dict(options)
            resume.updated_at = utcnow()

    async def save_version(
        self,
        owner_id: uuid.UUID,
        resume_id: uuid.UUID,
        *,
        content: dict[str, Any],
        label: str | None = None,
    ) -> VersionView:
        """Save the user's edits as a new version.

        A line they changed is theirs and may stand uncited; a line they left
        alone keeps what it cited. Anything cited must still be their evidence.
        """
        try:
            edited = ResumeContent.from_dict(content)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValidationError(f"that résumé could not be read: {exc}") from exc
        async with self._db.for_user(owner_id) as session:
            resume = await _owned(session, owner_id, resume_id)
            latest = await _latest_version(session, resume_id)
            previous = ResumeContent.from_dict(latest.content) if latest else None
        settled = mark_edits(previous, edited)
        try:
            assert_well_formed(settled)
        except ResumeError as exc:
            raise ValidationError(str(exc)) from exc
        await self._assert_owned(owner_id, settled, "your edit cites evidence that is not yours")
        return await self._add_version(
            owner_id,
            resume_id,
            content=settled,
            source=VersionSource.MANUAL,
            label=label or f"{resume.target_label} — edited",
            model_id=None,
            template_version=None,
        )

    async def revise(
        self,
        owner_id: uuid.UUID,
        resume_id: uuid.UUID,
        *,
        request: str,
        content: dict[str, Any],
    ) -> AsyncIterator[RevisionEvent]:
        """One exchange in the revision chat, streamed.

        Prose arrives as ``RevisionText``; the exchange ends with
        ``RevisionDone`` carrying a validated proposal, or ``RevisionFailed``
        with the error's stable code. Nothing is applied until the user says so.
        """
        try:
            current = ResumeContent.from_dict(content)
            assert_well_formed(current)
            async with self._db.for_user(owner_id) as session:
                resume = await _owned(session, owner_id, resume_id)
                if resume.snapshot is None:
                    raise ValidationError("this résumé has not been written yet")
                snapshot = TargetSnapshot.from_dict(resume.snapshot)
                coverage_rows = [_coverage_view(c) for c in resume.coverage]
                earlier = list(
                    (
                        await session.execute(
                            select(Revision)
                            .where(Revision.resume_id == resume_id)
                            .order_by(Revision.created_at.desc())
                            .limit(_CONVERSATION_TURNS)
                        )
                    ).scalars()
                )
            profile = await self._profile.snapshot(owner_id)
            inputs = {
                "target": snapshot.label,
                "requirements": requirements_block(snapshot),
                "coverage": _coverage_block(coverage_rows),
                "resume": json.dumps(current.to_dict(), ensure_ascii=False),
                "conversation": "\n".join(
                    f"Person: {r.request}\nYou: {r.reply}" for r in reversed(earlier)
                )
                or "(this is the first message)",
                "request": request,
                "evidence": _evidence_block(profile.evidence),
            }

            reply_parts: list[str] = []
            result: StreamResult[_Proposal] | None = None
            async for event in self._gateway.stream_structured(
                owner_id,
                task="resume.revise",
                template=load_template(*_REVISE),
                inputs=inputs,
                output_schema=_Proposal,
                marker=_MARKER,
                untrusted=_REVISE_UNTRUSTED,
            ):
                if isinstance(event, StreamText):
                    reply_parts.append(event.text)
                    yield RevisionText(event.text)
                else:
                    result = event
            if result is None:
                raise OutputInvalidError("the reply ended without a proposal")

            proposal: ResumeContent | None = None
            if result.value.changed and result.value.resume is not None:
                proposal = settle_revision(current, _content_of(result.value.resume))
                try:
                    assert_well_formed(proposal)
                    assert_written_lines_cited(proposal)
                except ResumeError as exc:
                    raise OutputInvalidError(f"the proposed revision was rejected: {exc}") from exc
                await self._assert_owned(
                    owner_id, proposal, "the proposed revision cited evidence that is not yours"
                )

            reply = "".join(reply_parts).strip()
            async with self._db.for_user(owner_id) as session:
                revision = Revision(
                    owner_id=owner_id,
                    resume_id=resume_id,
                    request=request,
                    reply=reply,
                    proposal=proposal.to_dict() if proposal else None,
                    model_id=result.model_id,
                    template_version=result.template_version,
                    created_at=utcnow(),
                )
                session.add(revision)
                await session.flush()
                revision_id = revision.id
            yield RevisionDone(revision_id=revision_id, reply=reply, proposal=proposal)
        except DomainError as exc:
            # The response is already streaming, so the failure travels as the
            # last event, in the same {code, message} terms as any error.
            log.warning("resume.revise_failed", resume_id=str(resume_id), code=str(exc.code))
            yield RevisionFailed(code=str(exc.code), message=exc.message)

    async def apply_revision(
        self, owner_id: uuid.UUID, resume_id: uuid.UUID, revision_id: uuid.UUID
    ) -> VersionView:
        """An accepted chat edit becomes a version (technical boundaries §6)."""
        async with self._db.for_user(owner_id) as session:
            resume = await _owned(session, owner_id, resume_id)
            revision = await session.get(Revision, revision_id)
            if revision is None or revision.resume_id != resume_id:
                raise NotFoundError("revision not found", revision_id=str(revision_id))
            if revision.proposal is None:
                raise ValidationError("that reply proposed no change to apply")
            if revision.applied_version_id is not None:
                raise ValidationError("that revision has already been applied")
            proposal = ResumeContent.from_dict(revision.proposal)
            model_id, template_version = revision.model_id, revision.template_version
            label = resume.target_label
        version = await self._add_version(
            owner_id,
            resume_id,
            content=proposal,
            source=VersionSource.CHAT,
            label=f"{label} — revised",
            model_id=model_id,
            template_version=template_version,
        )
        async with self._db.for_user(owner_id) as session:
            stored = await session.get(Revision, revision_id)
            if stored is not None:
                stored.applied_version_id = version.id
        return version

    # -- export -------------------------------------------------------------

    async def request_export(
        self, owner_id: uuid.UUID, resume_id: uuid.UUID, *, number: int
    ) -> ExportView:
        async with self._db.for_user(owner_id) as session:
            resume = await _owned(session, owner_id, resume_id)
            version = await session.execute(
                select(ResumeVersion).where(
                    ResumeVersion.resume_id == resume_id, ResumeVersion.number == number
                )
            )
            chosen = version.scalar_one_or_none()
            if chosen is None:
                raise NotFoundError("version not found", number=number)
            export = Export(
                owner_id=owner_id,
                version_id=chosen.id,
                template=resume.template,
                status="rendering",
                created_at=utcnow(),
            )
            session.add(export)
            await session.flush()
            return _export_view(export, download_url=None)

    async def export(self, owner_id: uuid.UUID, export_id: uuid.UUID) -> None:
        """The worker ``docs`` job: render, store, done. Failures are recorded."""
        async with self._db.for_user(owner_id) as session:
            export = await session.get(Export, export_id)
            if export is None or export.owner_id != owner_id:
                raise NotFoundError("export not found", export_id=str(export_id))
            if export.status != "rendering":
                return
            version = await session.get(ResumeVersion, export.version_id)
            if version is None:
                raise NotFoundError("version not found", version_id=str(export.version_id))
            resume = await session.get(Resume, version.resume_id)
            if resume is None:
                raise NotFoundError("résumé not found", resume_id=str(version.resume_id))
            content = ResumeContent.from_dict(version.content)
            template = Template(export.template)
            options = _options_of(resume.options)

        try:
            pdf = render_pdf(render_html(content, template=template, options=options))
        except (ValueError, OSError) as exc:
            await self._fail_export(
                owner_id,
                export_id,
                code="render_failed",
                message=f"The PDF could not be rendered: {exc}",
            )
            log.warning("resume.export_failed", export_id=str(export_id))
            return
        except Exception:
            await self._fail_export(
                owner_id, export_id, code="internal", message="Rendering stopped unexpectedly."
            )
            raise

        key = object_key(owner_id, "exports", f"{export_id}.pdf")
        self._store.put(key, pdf, "application/pdf")
        async with self._db.for_user(owner_id) as session:
            stored = await session.get(Export, export_id)
            if stored is not None:
                stored.status = "ready"
                stored.storage_key = key
                stored.finished_at = utcnow()

    async def get_export(self, owner_id: uuid.UUID, export_id: uuid.UUID) -> ExportView:
        async with self._db.for_user(owner_id) as session:
            export = await session.get(Export, export_id)
            if export is None or export.owner_id != owner_id:
                raise NotFoundError("export not found", export_id=str(export_id))
        url = self._store.signed_url(export.storage_key) if export.storage_key else None
        return _export_view(export, download_url=url)

    # -- internals ----------------------------------------------------------

    async def _generate(
        self, owner_id: uuid.UUID, resume_id: uuid.UUID, ref: TargetRef, options: Options
    ) -> None:
        snapshot = await self._target.snapshot(owner_id, ref)
        coverage_rows = await self._coverage(owner_id, snapshot)
        base = await self._profile.base_resume_text(owner_id)
        result = await self._gateway.run(
            owner_id,
            task="resume.generate",
            template=load_template(*_WRITE),
            inputs=await self._write_inputs(
                owner_id,
                label=snapshot.label,
                requirements=requirements_block(snapshot),
                coverage_rows=coverage_rows,
                options=options,
                base_resume=base or "(none uploaded)",
            ),
            output_schema=_Resume,
            untrusted=frozenset({"requirements", "evidence", "timeline", "base_resume"}),
        )
        content = _content_of(result.value)
        try:
            assert_well_formed(content)
            assert_written_lines_cited(content)
        except ResumeError as exc:
            raise OutputInvalidError(f"the written résumé was rejected: {exc}") from exc
        await self._assert_owned(owner_id, content, "the résumé cited evidence that is not yours")

        async with self._db.for_user(owner_id) as session:
            resume = await _owned(session, owner_id, resume_id)
            resume.snapshot = snapshot.to_dict()
            resume.target_label = snapshot.label[:400]
            resume.coverage = [_coverage_dict(c) for c in coverage_rows]
            resume.status = "ready"
            resume.updated_at = utcnow()
            label = resume.target_label
        await self._add_version(
            owner_id,
            resume_id,
            content=content,
            source=VersionSource.GENERATED,
            label=label,
            model_id=result.model_id,
            template_version=result.template_version,
        )
        async with self._db.for_user(owner_id) as session:
            await emit(
                session,
                EventName.RESUME_TAILORED,
                {"resume_id": str(resume_id), "target_kind": str(ref.kind)},
                owner_id=owner_id,
            )

    async def _coverage(
        self, owner_id: uuid.UUID, snapshot: TargetSnapshot
    ) -> tuple[CoverageView, ...]:
        assessment = await self._assessment.latest(owner_id)
        dimensions = assessment.dimensions if assessment else ()
        rows = coverage(
            requirements=[r.statement for r in snapshot.requirements],
            requirement_map=snapshot.requirement_map,
            scores={d.key: d.score for d in dimensions},
            targets={d.dimension_key: d.target_score for d in snapshot.dimensions},
            evidence={d.key: d.evidence_ids for d in dimensions},
        )
        notes = await self._notes(owner_id, {i for row in rows for i in row.evidence_ids})
        return tuple(_coverage_row(row, notes) for row in rows)

    async def _write_inputs(
        self,
        owner_id: uuid.UUID,
        *,
        label: str,
        requirements: str,
        coverage_rows: tuple[CoverageView, ...] | list[CoverageView],
        options: Options,
        base_resume: str,
    ) -> dict[str, str]:
        profile = await self._profile.snapshot(owner_id)
        timeline = "\n".join(
            f"- {p.title} at {p.company}, {p.started_on} to {p.ended_on or 'present'}"
            for p in profile.positions
        )
        return {
            "target": label,
            "requirements": requirements,
            "coverage": _coverage_block(coverage_rows) or "(worked out when writing)",
            "options": "\n".join(
                line
                for line, wanted in (
                    ("- Quantify bullets with numbers the evidence gives.", options.metrics),
                    ("- Order skills by what this job screens for.", options.reorder),
                    ("- Keep it to one page: at most 3 bullets a role.", options.trim),
                )
                if wanted
            )
            or "- No special instructions.",
            "timeline": timeline or "(no positions recorded)",
            "base_resume": base_resume,
            "evidence": _evidence_block(profile.evidence),
        }

    async def _assert_owned(
        self, owner_id: uuid.UUID, content: ResumeContent, message: str
    ) -> None:
        owned = await self._profile.evidence_ids(owner_id)
        try:
            assert_citations_exist(content.cited(), owned)
        except CitationError as exc:
            # An invented citation is how a fabricated claim gets in.
            raise EvidenceNotOwnedError(message, invented=sorted(exc.invented)) from exc

    async def _notes(self, owner_id: uuid.UUID, ids: set[str]) -> dict[str, EvidenceNote]:
        if not ids:
            return {}
        profile = await self._profile.snapshot(owner_id)
        return {
            str(e.id): EvidenceNote(str(e.id), e.reference, e.fact)
            for e in profile.evidence
            if str(e.id) in ids
        }

    async def _add_version(
        self,
        owner_id: uuid.UUID,
        resume_id: uuid.UUID,
        *,
        content: ResumeContent,
        source: VersionSource,
        label: str,
        model_id: str | None,
        template_version: str | None,
    ) -> VersionView:
        now = utcnow()
        async with self._db.for_user(owner_id) as session:
            resume = await _owned(session, owner_id, resume_id)
            latest = await _latest_version(session, resume_id)
            version = ResumeVersion(
                owner_id=owner_id,
                resume_id=resume_id,
                number=(latest.number if latest else 0) + 1,
                label=label[:200],
                content=content.to_dict(),
                source=str(source),
                model_id=model_id,
                template_version=template_version,
                created_at=now,
            )
            session.add(version)
            resume.updated_at = now
            await session.flush()
            await emit(
                session,
                EventName.RESUME_VERSION_SAVED,
                {"resume_id": str(resume_id), "number": version.number, "source": str(source)},
                owner_id=owner_id,
            )
            return _version_view(version)

    async def _fail_export(
        self, owner_id: uuid.UUID, export_id: uuid.UUID, *, code: str, message: str
    ) -> None:
        async with self._db.for_user(owner_id) as session:
            stored = await session.get(Export, export_id)
            if stored is not None:
                stored.status = "failed"
                stored.error_code = code
                stored.error_message = message
                stored.finished_at = utcnow()

    async def _fail(
        self, owner_id: uuid.UUID, resume_id: uuid.UUID, *, code: str, message: str
    ) -> None:
        async with self._db.for_user(owner_id) as session:
            resume = await session.get(Resume, resume_id)
            if resume is not None:
                resume.status = "failed"
                resume.error_code = code
                resume.error_message = message
                resume.updated_at = utcnow()


# --- helpers ---------------------------------------------------------------


async def _owned(session: Any, owner_id: uuid.UUID, resume_id: uuid.UUID) -> Resume:
    resume = await session.get(Resume, resume_id)
    if resume is None or resume.owner_id != owner_id:
        raise NotFoundError("résumé not found", resume_id=str(resume_id))
    return resume  # type: ignore[no-any-return]


async def _latest_version(session: Any, resume_id: uuid.UUID) -> ResumeVersion | None:
    rows = await session.execute(
        select(ResumeVersion)
        .where(ResumeVersion.resume_id == resume_id)
        .order_by(ResumeVersion.number.desc())
        .limit(1)
    )
    return rows.scalar_one_or_none()  # type: ignore[no-any-return]


def _content_of(model: _Resume) -> ResumeContent:
    return ResumeContent.from_dict(
        {
            "name": model.name,
            "headline": model.headline,
            "contact": model.contact,
            "summary": model.summary,
            "experience": [
                {
                    "title": p.title,
                    "org": p.org,
                    "when": p.when,
                    "bullets": [
                        {
                            "text": b.text,
                            "evidence_ids": b.evidence_ids,
                            # The model writes; it does not get to say otherwise.
                            "origin": str(Origin.WRITTEN),
                            "answers": b.answers,
                        }
                        for b in p.bullets
                    ],
                }
                for p in model.experience
            ],
            "skills": model.skills,
        }
    )


def _target_columns(ref: TargetRef) -> dict[str, uuid.UUID]:
    column = {
        TargetKind.MATCHED_POSTING: "job_posting_id",
        TargetKind.SUBSCRIPTION: "subscription_id",
        TargetKind.PRIVATE_POSTING: "private_posting_id",
    }[ref.kind]
    return {column: uuid.UUID(ref.id)}


def _ref_of(resume: Resume) -> TargetRef:
    reference = resume.job_posting_id or resume.subscription_id or resume.private_posting_id
    return TargetRef(TargetKind(resume.target_kind), str(reference))


def _options_dict(options: Options) -> dict[str, bool]:
    return {"metrics": options.metrics, "reorder": options.reorder, "trim": options.trim}


def _options_of(data: dict[str, Any]) -> Options:
    return Options(
        metrics=bool(data.get("metrics", True)),
        reorder=bool(data.get("reorder", True)),
        trim=bool(data.get("trim", False)),
    )


def _evidence_block(evidence: Any) -> str:
    return (
        "\n".join(f"[{e.id}] ({e.source}) {e.reference}: {e.fact}" for e in evidence)
        or "(no evidence)"
    )


def _coverage_row(row: Coverage, notes: dict[str, EvidenceNote]) -> CoverageView:
    return CoverageView(
        requirement=row.requirement,
        verdict=str(row.verdict),
        dimension_key=row.dimension_key,
        evidence=tuple(notes[i] for i in row.evidence_ids if i in notes),
    )


def _coverage_dict(row: CoverageView) -> dict[str, Any]:
    return {
        "requirement": row.requirement,
        "verdict": row.verdict,
        "dimension_key": row.dimension_key,
        "evidence": [{"id": e.id, "reference": e.reference, "fact": e.fact} for e in row.evidence],
    }


def _coverage_view(data: dict[str, Any]) -> CoverageView:
    return CoverageView(
        requirement=data["requirement"],
        verdict=data["verdict"],
        dimension_key=data.get("dimension_key"),
        evidence=tuple(EvidenceNote(**e) for e in data.get("evidence", [])),
    )


def _coverage_block(rows: tuple[CoverageView, ...] | list[CoverageView]) -> str:
    return "\n".join(f"- {row.verdict}: {row.requirement}" for row in rows)


def _summary(resume: Resume, *, latest_version: int | None) -> ResumeSummaryView:
    return ResumeSummaryView(
        id=resume.id,
        target=_ref_of(resume),
        label=resume.target_label,
        status=resume.status,
        error_code=resume.error_code,
        error_message=resume.error_message,
        latest_version=latest_version,
        created_at=resume.created_at,
        updated_at=resume.updated_at,
    )


def _version_view(version: ResumeVersion) -> VersionView:
    return VersionView(
        id=version.id,
        number=version.number,
        label=version.label,
        source=VersionSource(version.source),
        model_id=version.model_id,
        created_at=version.created_at,
    )


def _revision_view(revision: Revision) -> RevisionView:
    return RevisionView(
        id=revision.id,
        request=revision.request,
        reply=revision.reply,
        has_proposal=revision.proposal is not None,
        applied_version_id=revision.applied_version_id,
        created_at=revision.created_at,
    )


def _export_view(export: Export, *, download_url: str | None) -> ExportView:
    return ExportView(
        id=export.id,
        version_id=export.version_id,
        template=Template(export.template),
        status=export.status,
        error_code=export.error_code,
        error_message=export.error_message,
        download_url=download_url,
    )
