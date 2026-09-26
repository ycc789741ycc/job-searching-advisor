"""Skill assessment, follow-up questions and fit.

Two reports come out of here: the radar (this user's dimensions and scores)
and the bubble sizes (fit between this user and each role).

Everything stored is an immutable snapshot recording the profile version, the
model and the prompt template that produced it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from advisor.assessment.domain import (
    DEFAULT_MATCHES,
    MAX_DIMENSIONS,
    MIN_DIMENSIONS,
    ClosingLifts,
    DimensionCountError,
    MatchCandidate,
    SkillGap,
    TargetScore,
    UncoveredRequirement,
    assert_ids_unique,
    assert_within_bounds,
    closing_lifts,
    derive_lineage,
    dropped_ids,
    evaluate,
    needs_follow_up,
    rank_matches,
)
from advisor.assessment.domain import (
    DimensionScore as DimensionValue,
)
from advisor.assessment.infra.models import (
    DimensionLineage,
    DimensionScore,
    FollowUpQuestion,
    RoleFit,
    SkillAssessment,
    SkillDimension,
)
from advisor.market import MarketService, PostingView, SalaryRange, Visibility
from advisor.profile import CitationError, ProfileService, assert_citations_exist
from advisor.rolemap import RequirementView, RoleMapService, RoleView
from kernel.ai_gateway import AiGateway
from kernel.ai_gateway import load as load_template
from kernel.db import Database
from kernel.db.base import utcnow
from kernel.errors import DimensionCountError as DimensionCountFailure
from kernel.errors import EvidenceNotOwnedError, NotFoundError, ValidationError
from kernel.logging import get_logger
from kernel.outbox import EventName, emit

__all__ = [
    "AssessmentService",
    "AssessmentView",
    "DimensionView",
    "FitView",
    "MatchedPostingView",
    "QuestionView",
]

log = get_logger(__name__)


# --- AI output schemas -----------------------------------------------------


class _Dimension(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    short_name: str = Field(default="", max_length=32)
    score: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0.0, le=1.0)
    read: str
    evidence_ids: list[str] = Field(default_factory=list)


class _Assessment(BaseModel):
    dimensions: list[_Dimension] = Field(min_length=MIN_DIMENSIONS, max_length=MAX_DIMENSIONS)


class _Question(BaseModel):
    dimension_id: str
    text: str
    why: str
    options: list[str] = Field(min_length=2, max_length=4)


class _Questions(BaseModel):
    questions: list[_Question] = Field(max_length=5)


class _Mapping(BaseModel):
    requirement_statement: str
    dimension_id: str | None = None


class _Target(BaseModel):
    dimension_id: str
    target: int = Field(ge=0, le=100)


class _PostingRequirement(BaseModel):
    statement: str = Field(min_length=1, max_length=400)
    weight: float = Field(ge=0.0, le=1.0)
    expected_level: str = Field(pattern="^(familiar|proficient|advanced|expert)$")


class _PostingRequirements(BaseModel):
    requirements: list[_PostingRequirement] = Field(min_length=3, max_length=12)


class _Projection(BaseModel):
    mappings: list[_Mapping]
    target_scores: list[_Target]
    reasoning: str


# --- views -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DimensionView:
    key: str
    name: str
    short_name: str
    score: int
    confidence: float
    read: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AssessmentView:
    id: uuid.UUID
    profile_version: int
    model_id: str
    template_version: str
    created_at: datetime
    dimensions: tuple[DimensionView, ...]


@dataclass(frozen=True, slots=True)
class QuestionView:
    id: uuid.UUID
    dimension_key: str
    text: str
    why: str
    options: tuple[str, ...]
    answer: str | None


@dataclass(frozen=True, slots=True)
class FitView:
    role_id: uuid.UUID | None
    private_posting_id: uuid.UUID | None
    score: int
    reasoning: str
    gaps: tuple[dict[str, Any], ...]
    uncovered: tuple[dict[str, Any], ...]
    model_id: str
    created_at: datetime
    assessment_id: uuid.UUID | None = None
    target_profile: dict[str, int] = field(default_factory=dict)
    # What the fit was projected from; empty for fits taken before these were
    # recorded.
    requirements: tuple[RequirementView, ...] = ()
    requirement_map: dict[str, str | None] = field(default_factory=dict)

    def lifts(self) -> ClosingLifts:
        """Fit points each gap is worth, by the fit's own arithmetic."""
        return closing_lifts(
            gaps=[
                SkillGap(g["dimension_key"], g["user_score"], g["target_score"]) for g in self.gaps
            ],
            uncovered=[UncoveredRequirement(u["statement"], u["weight"]) for u in self.uncovered],
        )


@dataclass(frozen=True, slots=True)
class MatchedPostingView:
    """One opening inside one of the user's roles, ranked by that role's fit."""

    posting_id: uuid.UUID
    role_id: uuid.UUID
    role_name: str
    title: str
    company_name: str
    location: str | None
    url: str | None
    salary: SalaryRange | None
    fit: int | None
    subscription_id: uuid.UUID | None
    # The crawl source kind (atsBoard, jsonLd, publicApi); never a site that
    # forbids crawling (domain decision 6).
    source_kind: str | None = None


class AssessmentService:
    def __init__(
        self,
        database: Database,
        *,
        profile: ProfileService,
        rolemap: RoleMapService,
        market: MarketService,
        gateway: AiGateway,
        confidence_threshold: float,
    ) -> None:
        self._db = database
        self._profile = profile
        self._rolemap = rolemap
        self._market = market
        self._gateway = gateway
        self._threshold = confidence_threshold

    # -- cost ---------------------------------------------------------------

    async def estimate_cost(self, owner_id: uuid.UUID) -> dict[str, Any]:
        """Priced before anything is spent, for the first-run confirmation."""
        snapshot = await self._profile.snapshot(owner_id)
        if not snapshot.evidence:
            raise ValidationError(
                "connect a source or upload a resume before analysing", evidence=0
            )
        estimate = await self._gateway.estimate(
            owner_id,
            task="assessment.run",
            template=load_template("skill_assessment", "v1"),
            inputs=_assessment_inputs(snapshot, existing=()),
            untrusted=frozenset({"evidence", "timeline"}),
        )
        return {
            "cost_usd": str(estimate.cost_usd),
            "model_id": estimate.model_id,
            "input_tokens": estimate.input_tokens,
            "rate_is_published": estimate.rate_is_published,
        }

    # -- the strength report ------------------------------------------------

    async def run(self, owner_id: uuid.UUID) -> AssessmentView:
        snapshot = await self._profile.snapshot(owner_id)
        if not snapshot.evidence:
            raise ValidationError("there is no evidence to analyse yet", evidence=0)

        existing = await self._existing_dimensions(owner_id)
        result = await self._gateway.run(
            owner_id,
            task="assessment.run",
            template=load_template("skill_assessment", "v1"),
            inputs=_assessment_inputs(snapshot, existing=tuple(existing.items())),
            output_schema=_Assessment,
            untrusted=frozenset({"evidence", "timeline"}),
        )

        owned_evidence = await self._profile.evidence_ids(owner_id)
        dimensions: list[DimensionValue] = []
        for item in result.value.dimensions:
            try:
                assert_citations_exist(set(item.evidence_ids), owned_evidence)
            except CitationError as exc:
                # An invented citation is how a fabricated claim gets in.
                raise EvidenceNotOwnedError(
                    "the analysis cited evidence that is not in your profile",
                    invented=sorted(exc.invented),
                ) from exc
            dimensions.append(
                DimensionValue(
                    dimension_id=item.id,
                    name=item.name,
                    short_name=item.short_name or item.name[:24],
                    score=item.score,
                    confidence=item.confidence,
                    read=item.read,
                    evidence_ids=tuple(item.evidence_ids),
                )
            )

        try:
            assert_within_bounds(dimensions)
            assert_ids_unique(dimensions)
        except DimensionCountError as exc:
            raise DimensionCountFailure(str(exc)) from exc
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        assessment_id = await self._store(
            owner_id,
            snapshot_version=snapshot.version,
            dimensions=dimensions,
            existing=existing,
            model_id=result.model_id,
            template_version=result.template_version,
        )

        thin = needs_follow_up(dimensions, threshold=self._threshold)
        if thin:
            await self._raise_questions(owner_id, assessment_id, thin, snapshot)

        return await self.latest(owner_id) or _never()

    async def latest(self, owner_id: uuid.UUID) -> AssessmentView | None:
        async with self._db.for_user(owner_id) as session:
            rows = await session.execute(
                select(SkillAssessment)
                .where(SkillAssessment.owner_id == owner_id)
                .order_by(SkillAssessment.created_at.desc())
                .limit(1)
            )
            assessment = rows.scalar_one_or_none()
            if assessment is None:
                return None

            score_rows = await session.execute(
                select(DimensionScore).where(DimensionScore.assessment_id == assessment.id)
            )
            scores = list(score_rows.scalars())
            dimension_rows = await session.execute(
                select(SkillDimension).where(SkillDimension.owner_id == owner_id)
            )
            names = {d.key: (d.name, d.short_name) for d in dimension_rows.scalars()}

            return AssessmentView(
                id=assessment.id,
                profile_version=assessment.profile_version,
                model_id=assessment.model_id,
                template_version=assessment.template_version,
                created_at=assessment.created_at,
                dimensions=tuple(
                    DimensionView(
                        key=score.dimension_key,
                        name=names.get(score.dimension_key, (score.dimension_key, ""))[0],
                        short_name=names.get(score.dimension_key, ("", ""))[1],
                        score=score.score,
                        confidence=score.confidence,
                        read=score.read,
                        evidence_ids=tuple(score.evidence_ids),
                    )
                    for score in sorted(scores, key=lambda s: s.dimension_key)
                ),
            )

    async def history(self, owner_id: uuid.UUID) -> list[AssessmentView]:
        """Comparing assessments is how progress is shown; stable ids make it work."""
        async with self._db.for_user(owner_id) as session:
            rows = await session.execute(
                select(SkillAssessment.id)
                .where(SkillAssessment.owner_id == owner_id)
                .order_by(SkillAssessment.created_at.desc())
            )
            ids = list(rows.scalars())
        views = [await self._view_of(owner_id, assessment_id) for assessment_id in ids]
        return [view for view in views if view is not None]

    # -- follow-up questions ------------------------------------------------

    async def questions(
        self, owner_id: uuid.UUID, *, unanswered_only: bool = True
    ) -> list[QuestionView]:
        async with self._db.for_user(owner_id) as session:
            query = select(FollowUpQuestion).where(FollowUpQuestion.owner_id == owner_id)
            if unanswered_only:
                query = query.where(FollowUpQuestion.answered_at.is_(None))
            rows = await session.execute(query.order_by(FollowUpQuestion.created_at))
            return [
                QuestionView(
                    id=q.id,
                    dimension_key=q.dimension_key,
                    text=q.text,
                    why=q.why,
                    options=tuple(q.options),
                    answer=q.answer,
                )
                for q in rows.scalars()
            ]

    async def answer(self, owner_id: uuid.UUID, question_id: uuid.UUID, answer: str) -> None:
        """An answer becomes self-reported Evidence and bumps the profile."""
        async with self._db.for_user(owner_id) as session:
            question = await session.get(FollowUpQuestion, question_id)
            if question is None or question.owner_id != owner_id:
                raise NotFoundError("question not found", question_id=str(question_id))
            question.answer = answer
            question.answered_at = utcnow()
            text, key = question.text, str(question.id)
            await emit(
                session,
                EventName.QUESTION_ANSWERED,
                {"question_id": key, "dimension": question.dimension_key},
                owner_id=owner_id,
            )

        await self._profile.record_answer(owner_id, question_id=key, question=text, answer=answer)

    # -- fit ----------------------------------------------------------------

    async def compute_fits(self, owner_id: uuid.UUID) -> list[FitView]:
        """One projection per User x Role, stored with its reasoning."""
        assessment = await self.latest(owner_id)
        if assessment is None:
            raise ValidationError("run an analysis before scoring roles")

        roles = await self._rolemap.roles(owner_id)
        if not roles:
            return []

        for role in roles:
            if not role.requirements:
                continue
            await self._project(
                owner_id,
                assessment,
                name=role.name,
                requirements=role.requirements,
                role_id=role.id,
            )

        async with self._db.for_user(owner_id) as session:
            await emit(
                session,
                EventName.ROLE_FITS_COMPUTED,
                {"roles": len(roles)},
                owner_id=owner_id,
            )
        return await self.fits(owner_id)

    async def fits(self, owner_id: uuid.UUID) -> list[FitView]:
        """The current fit per role — the bubble sizes."""
        async with self._db.for_user(owner_id) as session:
            rows = await session.execute(
                select(RoleFit)
                .where(RoleFit.owner_id == owner_id)
                .order_by(RoleFit.created_at.desc())
            )
            seen: set[Any] = set()
            latest: list[FitView] = []
            for row in rows.scalars():
                target = row.role_id or row.private_posting_id
                if target in seen:
                    continue
                seen.add(target)
                latest.append(_fit_view(row))
            return latest

    async def fit_for_private_posting(self, owner_id: uuid.UUID, posting_id: uuid.UUID) -> FitView:
        """Fit against a JD the user pasted, reading its requirements first.

        A pasted JD has no Role, so its requirements are read from its own text
        (on the user's key), then projected onto the user's dimensions like any
        role's. A fit already taken against the current analysis is reused, so
        planning and writing for the same JD pay for this once.
        """
        assessment = await self.latest(owner_id)
        if assessment is None:
            raise ValidationError("run an analysis before scoring a job description")
        for fit in await self.fits(owner_id):
            if fit.private_posting_id == posting_id and fit.assessment_id == assessment.id:
                return fit

        posting = await self._market.private_posting(owner_id, posting_id)
        extraction = await self._gateway.run(
            owner_id,
            task="assessment.posting_requirements",
            template=load_template("posting_requirements", "v1"),
            inputs=_posting_inputs(posting),
            output_schema=_PostingRequirements,
            untrusted=frozenset({"posting"}),
        )
        requirements = tuple(
            RequirementView(r.statement, r.weight, r.expected_level)
            for r in extraction.value.requirements
        )
        await self._project(
            owner_id,
            assessment,
            name=f"{posting.title} at {posting.company_name}",
            requirements=requirements,
            private_posting_id=posting_id,
        )
        for fit in await self.fits(owner_id):
            if fit.private_posting_id == posting_id:
                return fit
        raise NotFoundError("the fit disappeared immediately after being written")

    async def estimate_private_fit(self, owner_id: uuid.UUID, posting_id: uuid.UUID) -> Decimal:
        """What scoring a pasted JD would cost; nothing when it is already scored."""
        assessment = await self.latest(owner_id)
        if assessment is None:
            raise ValidationError("run an analysis before scoring a job description")
        for fit in await self.fits(owner_id):
            if fit.private_posting_id == posting_id and fit.assessment_id == assessment.id:
                return Decimal(0)
        posting = await self._market.private_posting(owner_id, posting_id)
        extraction = await self._gateway.estimate(
            owner_id,
            task="assessment.posting_requirements",
            template=load_template("posting_requirements", "v1"),
            inputs=_posting_inputs(posting),
            untrusted=frozenset({"posting"}),
        )
        # The projection's requirements are not known yet; the posting's own
        # text stands in for them, which over- rather than under-estimates.
        projection = await self._gateway.estimate(
            owner_id,
            task="assessment.fit",
            template=load_template("fit_projection", "v1"),
            inputs={
                "dimensions": _dimensions_block(assessment),
                "role_name": posting.title,
                "requirements": posting.description,
            },
            untrusted=frozenset({"requirements"}),
        )
        return extraction.cost_usd + projection.cost_usd

    async def _project(
        self,
        owner_id: uuid.UUID,
        assessment: AssessmentView,
        *,
        name: str,
        requirements: tuple[RequirementView, ...],
        role_id: uuid.UUID | None = None,
        private_posting_id: uuid.UUID | None = None,
    ) -> None:
        """Map requirements onto this user's dimensions, and store the fit."""
        user_scores = {d.key: d.score for d in assessment.dimensions}
        known_keys = set(user_scores)
        projection = await self._gateway.run(
            owner_id,
            task="assessment.fit",
            template=load_template("fit_projection", "v1"),
            inputs={
                "dimensions": _dimensions_block(assessment),
                "role_name": name,
                "requirements": "\n".join(
                    f"- {r.statement} (weight {r.weight}, expects {r.expected_level})"
                    for r in requirements
                ),
            },
            output_schema=_Projection,
            untrusted=frozenset({"requirements"}),
        )

        targets = [
            TargetScore(dimension_id=t.dimension_id, target=t.target)
            for t in projection.value.target_scores
            # A target for a dimension this user does not have is the model
            # drifting, not a new axis.
            if t.dimension_id in known_keys
        ]
        uncovered = _uncovered_from(projection.value, requirements, known_keys)
        fit = evaluate(user_scores=user_scores, targets=targets, uncovered=uncovered)
        statements = {r.statement for r in requirements}
        requirement_map: dict[str, str | None] = {statement: None for statement in statements}
        for mapping in projection.value.mappings:
            if mapping.requirement_statement in statements:
                requirement_map[mapping.requirement_statement] = (
                    mapping.dimension_id if mapping.dimension_id in known_keys else None
                )

        await self._store_fit(
            owner_id,
            assessment_id=assessment.id,
            role_id=role_id,
            private_posting_id=private_posting_id,
            fit=fit,
            targets=targets,
            requirements=requirements,
            requirement_map=requirement_map,
            reasoning=projection.value.reasoning,
            model_id=projection.model_id,
            template_version=projection.template_version,
        )

    async def matched_postings(
        self, owner_id: uuid.UUID, *, limit: int = DEFAULT_MATCHES
    ) -> list[MatchedPostingView]:
        """The best openings inside the user's analysed roles.

        Ranked by the role's current fit; no AI runs here. Pasted JDs are left
        out — they are the user's own, shown as "My own JD", not as a match —
        and each row says whether the user already watches that role there.
        """
        fit_by_role = {f.role_id: f.score for f in await self.fits(owner_id) if f.role_id}
        subscriptions = await self._market.subscriptions(owner_id)

        by_posting: dict[str, tuple[RoleView, Any]] = {}
        candidates: list[MatchCandidate] = []
        for role, postings in await self._rolemap.role_postings(owner_id):
            for posting in postings:
                if posting.visibility is not Visibility.SHARED:
                    continue
                by_posting[str(posting.id)] = (role, posting)
                candidates.append(
                    MatchCandidate(
                        posting_id=str(posting.id),
                        role_id=str(role.id),
                        role_name=role.name,
                        company_name=posting.company_name,
                        title=posting.title,
                        fit=fit_by_role.get(role.id),
                    )
                )

        try:
            ranked = rank_matches(candidates, limit=limit)
        except ValueError as exc:
            raise ValidationError(str(exc), limit=limit) from exc

        matched: list[MatchedPostingView] = []
        for candidate in ranked:
            role, posting = by_posting[candidate.posting_id]
            watching = next(
                (
                    s.id
                    for s in subscriptions
                    if s.company_id == posting.company_id
                    and (s.role_id == role.id or s.role_title.casefold() == role.name.casefold())
                ),
                None,
            )
            matched.append(
                MatchedPostingView(
                    posting_id=posting.id,
                    role_id=role.id,
                    role_name=role.name,
                    title=posting.title,
                    company_name=posting.company_name,
                    location=posting.location,
                    url=posting.url,
                    salary=posting.salary,
                    fit=candidate.fit,
                    subscription_id=watching,
                    source_kind=posting.source_kind,
                )
            )
        return matched

    # -- internals ----------------------------------------------------------

    async def _existing_dimensions(self, owner_id: uuid.UUID) -> dict[str, str]:
        async with self._db.for_user(owner_id) as session:
            rows = await session.execute(
                select(SkillDimension.key, SkillDimension.name).where(
                    SkillDimension.owner_id == owner_id
                )
            )
            return {key: name for key, name in rows.all()}

    async def _store(
        self,
        owner_id: uuid.UUID,
        *,
        snapshot_version: int,
        dimensions: list[DimensionValue],
        existing: dict[str, str],
        model_id: str,
        template_version: str,
    ) -> uuid.UUID:
        lineage = derive_lineage(existing, dimensions)
        dropped = dropped_ids(existing, dimensions)

        async with self._db.for_user(owner_id) as session:
            assessment = SkillAssessment(
                owner_id=owner_id,
                profile_version=snapshot_version,
                model_id=model_id,
                template_version=template_version,
            )
            session.add(assessment)
            await session.flush()

            known = await session.execute(
                select(SkillDimension).where(SkillDimension.owner_id == owner_id)
            )
            by_key = {row.key: row for row in known.scalars()}

            for dimension in dimensions:
                row = by_key.get(dimension.dimension_id)
                if row is None:
                    session.add(
                        SkillDimension(
                            owner_id=owner_id,
                            key=dimension.dimension_id,
                            name=dimension.name,
                            short_name=dimension.short_name,
                        )
                    )
                else:
                    row.name = dimension.name
                    row.short_name = dimension.short_name
                    row.retired_at = None

                session.add(
                    DimensionScore(
                        owner_id=owner_id,
                        assessment_id=assessment.id,
                        dimension_key=dimension.dimension_id,
                        score=dimension.score,
                        confidence=dimension.confidence,
                        read=dimension.read,
                        evidence_ids=list(dimension.evidence_ids),
                    )
                )

            for entry in lineage:
                session.add(
                    DimensionLineage(
                        owner_id=owner_id,
                        assessment_id=assessment.id,
                        kind=str(entry.kind),
                        dimension_key=entry.dimension_id,
                        from_keys=list(entry.from_ids),
                        previous_name=entry.previous_name,
                    )
                )

            # A dimension that stops appearing is retired with a record, never
            # silently orphaned — old radar points still resolve.
            for key in dropped:
                row = by_key.get(key)
                if row is not None:
                    row.retired_at = utcnow()
                session.add(
                    DimensionLineage(
                        owner_id=owner_id,
                        assessment_id=assessment.id,
                        kind="merged",
                        dimension_key=key,
                        from_keys=[],
                        previous_name=existing.get(key),
                    )
                )

            await emit(
                session,
                EventName.ASSESSMENT_COMPLETED,
                {
                    "assessment_id": str(assessment.id),
                    "dimensions": len(dimensions),
                    "model_id": model_id,
                },
                owner_id=owner_id,
            )
            if lineage or dropped:
                await emit(
                    session,
                    EventName.DIMENSIONS_CHANGED,
                    {"added_or_renamed": len(lineage), "retired": len(dropped)},
                    owner_id=owner_id,
                )
            return assessment.id

    async def _raise_questions(
        self,
        owner_id: uuid.UUID,
        assessment_id: uuid.UUID,
        thin: list[DimensionValue],
        snapshot: Any,
    ) -> None:
        block = "\n".join(
            f"- {d.dimension_id} ({d.name}): scored {d.score}, confidence "
            f"{d.confidence:.2f}. {d.read}"
            for d in thin
        )
        evidence_block = _evidence_block(snapshot)
        result = await self._gateway.run(
            owner_id,
            task="assessment.questions",
            template=load_template("follow_up_questions", "v1"),
            inputs={"low_confidence_dimensions": block, "evidence": evidence_block},
            output_schema=_Questions,
            untrusted=frozenset({"evidence"}),
        )

        known = {d.dimension_id for d in thin}
        async with self._db.for_user(owner_id) as session:
            stored = 0
            for question in result.value.questions:
                if question.dimension_id not in known:
                    continue
                session.add(
                    FollowUpQuestion(
                        owner_id=owner_id,
                        assessment_id=assessment_id,
                        dimension_key=question.dimension_id,
                        text=question.text,
                        why=question.why,
                        options=list(question.options),
                    )
                )
                stored += 1
            if stored:
                await emit(
                    session,
                    EventName.QUESTIONS_RAISED,
                    {"count": stored, "assessment_id": str(assessment_id)},
                    owner_id=owner_id,
                )

    async def _store_fit(
        self,
        owner_id: uuid.UUID,
        *,
        assessment_id: uuid.UUID,
        role_id: uuid.UUID | None,
        private_posting_id: uuid.UUID | None,
        fit: Any,
        targets: list[TargetScore],
        requirements: tuple[RequirementView, ...],
        requirement_map: dict[str, str | None],
        reasoning: str,
        model_id: str,
        template_version: str,
    ) -> None:
        if (role_id is None) == (private_posting_id is None):
            raise ValidationError("a fit is for exactly one role or one posting")
        async with self._db.for_user(owner_id) as session:
            session.add(
                RoleFit(
                    owner_id=owner_id,
                    assessment_id=assessment_id,
                    role_id=role_id,
                    private_posting_id=private_posting_id,
                    requirements=[
                        {
                            "statement": r.statement,
                            "weight": r.weight,
                            "expected_level": r.expected_level,
                        }
                        for r in requirements
                    ],
                    requirement_map=requirement_map,
                    score=fit.score,
                    reasoning=reasoning,
                    target_profile={t.dimension_id: t.target for t in targets},
                    gaps=[
                        {
                            "dimension_key": gap.dimension_id,
                            "user_score": gap.user_score,
                            "target_score": gap.target_score,
                            "delta": gap.delta,
                        }
                        for gap in fit.gaps
                    ],
                    uncovered=[
                        {"statement": u.statement, "weight": u.weight} for u in fit.uncovered
                    ],
                    model_id=model_id,
                    template_version=template_version,
                )
            )

    async def _view_of(
        self, owner_id: uuid.UUID, assessment_id: uuid.UUID
    ) -> AssessmentView | None:
        async with self._db.for_user(owner_id) as session:
            assessment = await session.get(SkillAssessment, assessment_id)
            if assessment is None:
                return None
            score_rows = await session.execute(
                select(DimensionScore).where(DimensionScore.assessment_id == assessment_id)
            )
            dimension_rows = await session.execute(
                select(SkillDimension).where(SkillDimension.owner_id == owner_id)
            )
            names = {d.key: (d.name, d.short_name) for d in dimension_rows.scalars()}
            return AssessmentView(
                id=assessment.id,
                profile_version=assessment.profile_version,
                model_id=assessment.model_id,
                template_version=assessment.template_version,
                created_at=assessment.created_at,
                dimensions=tuple(
                    DimensionView(
                        key=s.dimension_key,
                        name=names.get(s.dimension_key, (s.dimension_key, ""))[0],
                        short_name=names.get(s.dimension_key, ("", ""))[1],
                        score=s.score,
                        confidence=s.confidence,
                        read=s.read,
                        evidence_ids=tuple(s.evidence_ids),
                    )
                    for s in sorted(score_rows.scalars(), key=lambda s: s.dimension_key)
                ),
            )


def _assessment_inputs(snapshot: Any, *, existing: tuple[tuple[str, str], ...]) -> dict[str, str]:
    return {
        "timeline": _timeline_block(snapshot),
        "evidence": _evidence_block(snapshot),
        "existing_dimensions": (
            "\n".join(f"- {key}: {name}" for key, name in existing) or "(none yet)"
        ),
    }


def _timeline_block(snapshot: Any) -> str:
    if not snapshot.positions:
        return "(no positions recorded)"
    lines = [
        f"- {p.title} at {p.company}, {p.started_on} to {p.ended_on or 'present'}"
        for p in snapshot.positions
    ]
    lines.append(
        f"Total experience, overlaps counted once: {snapshot.total_experience_months} months"
    )
    return "\n".join(lines)


def _evidence_block(snapshot: Any) -> str:
    return "\n".join(f"[{e.id}] ({e.source}) {e.reference}: {e.fact}" for e in snapshot.evidence)


def _uncovered_from(
    projection: _Projection, requirements: tuple[RequirementView, ...], known_keys: set[str]
) -> list[UncoveredRequirement]:
    """Requirements that map to no dimension of this user's.

    Never dropped: no evidence at all is a different thing from a low score.
    """
    weights = {r.statement: r.weight for r in requirements}
    uncovered: list[UncoveredRequirement] = []
    mapped = {m.requirement_statement for m in projection.mappings if m.dimension_id in known_keys}
    for statement, weight in weights.items():
        if statement not in mapped:
            uncovered.append(UncoveredRequirement(statement=statement, weight=weight))
    return uncovered


def _never() -> AssessmentView:
    raise NotFoundError("the assessment disappeared immediately after being written")


def _dimensions_block(assessment: AssessmentView) -> str:
    return "\n".join(
        f"- {d.key}: {d.name} — scored {d.score}/100 (confidence {d.confidence:.2f})"
        for d in assessment.dimensions
    )


def _posting_inputs(posting: PostingView) -> dict[str, str]:
    return {
        "posting": (
            f"Title: {posting.title}\nCompany: {posting.company_name}\n"
            f"Location: {posting.location or 'not given'}\n\n{posting.description}"
        )
    }


def _fit_view(row: RoleFit) -> FitView:
    return FitView(
        role_id=row.role_id,
        private_posting_id=row.private_posting_id,
        score=row.score,
        reasoning=row.reasoning,
        gaps=tuple(row.gaps),
        uncovered=tuple(row.uncovered),
        model_id=row.model_id,
        created_at=row.created_at,
        assessment_id=row.assessment_id,
        target_profile=dict(row.target_profile),
        requirements=tuple(
            RequirementView(r["statement"], r["weight"], r["expected_level"])
            for r in row.requirements or []
        ),
        requirement_map=dict(row.requirement_map or {}),
    )
