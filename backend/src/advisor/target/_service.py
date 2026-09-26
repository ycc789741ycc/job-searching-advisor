"""Targets: what a gap plan or a résumé is aimed at (domain decision 16).

A Target is a value, not a table. This module resolves one — a matched
posting, a subscribed role, or a pasted JD — through the other modules' public
surfaces and freezes what it requires and how the user measures up into a
``TargetSnapshot``. The plan or résumé that keys on it stores that snapshot.

Only a pasted JD may cost anything to resolve: it has no Role, so its
requirements are read and scored on the user's key the first time.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from advisor.assessment import AssessmentService, FitView
from advisor.market import MarketService, SalaryRange
from advisor.rolemap import RoleMapService, RoleView
from advisor.target._domain import (
    DimensionGap,
    Requirement,
    RequirementBasis,
    TargetError,
    TargetKind,
    TargetRef,
    TargetSnapshot,
    UncoveredGap,
)
from kernel.db.base import utcnow
from kernel.errors import NotFoundError, TargetUnusableError

__all__ = [
    "DimensionGap",
    "TargetKind",
    "TargetOptionView",
    "TargetPreview",
    "TargetRef",
    "TargetService",
    "TargetSnapshot",
    "UncoveredGap",
    "requirements_block",
]

# Where a subscription or pasted JD came from, next to the crawl source kinds
# a matched posting carries.
WATCHLIST = "watchlist"
PASTED = "pasted"


@dataclass(frozen=True, slots=True)
class TargetOptionView:
    """One row of the "Plan a route to" / "Write for" pickers."""

    kind: TargetKind
    id: uuid.UUID
    title: str
    role_name: str | None
    role_id: uuid.UUID | None
    company_name: str
    fit: int | None
    salary: SalaryRange | None
    source_kind: str | None
    url: str | None
    subscription_id: uuid.UUID | None

    @property
    def label(self) -> str:
        return f"{self.role_name or self.title} · {self.company_name}"


@dataclass(frozen=True, slots=True)
class TargetPreview:
    """What pricing a plan needs, resolved without spending anything.

    ``snapshot`` is None for a pasted JD not yet scored against the current
    analysis; ``pending_cost_usd`` is then what scoring it will cost.
    """

    label: str
    snapshot: TargetSnapshot | None
    requirements_text: str
    pending_cost_usd: Decimal


class TargetService:
    def __init__(
        self,
        *,
        assessment: AssessmentService,
        market: MarketService,
        rolemap: RoleMapService,
    ) -> None:
        self._assessment = assessment
        self._market = market
        self._rolemap = rolemap

    async def options(self, owner_id: uuid.UUID) -> list[TargetOptionView]:
        """Top matched openings, then watched roles, then pasted JDs."""
        fits = await self._assessment.fits(owner_id)
        role_fit = {f.role_id: f.score for f in fits if f.role_id}
        posting_fit = {f.private_posting_id: f.score for f in fits if f.private_posting_id}
        roles = await self._rolemap.roles(owner_id)

        options = [
            TargetOptionView(
                kind=TargetKind.MATCHED_POSTING,
                id=match.posting_id,
                title=match.title,
                role_name=match.role_name,
                role_id=match.role_id,
                company_name=match.company_name,
                fit=match.fit,
                salary=match.salary,
                source_kind=match.source_kind,
                url=match.url,
                subscription_id=match.subscription_id,
            )
            for match in await self._assessment.matched_postings(owner_id)
        ]
        for subscription in await self._market.subscriptions(owner_id):
            role = _role_for(roles, subscription.role_id, subscription.role_title)
            options.append(
                TargetOptionView(
                    kind=TargetKind.SUBSCRIPTION,
                    id=subscription.id,
                    title=subscription.role_title,
                    role_name=role.name if role else subscription.role_title or None,
                    role_id=role.id if role else None,
                    company_name=subscription.company_name,
                    fit=role_fit.get(role.id) if role else None,
                    salary=None,
                    source_kind=WATCHLIST,
                    url=subscription.url,
                    subscription_id=subscription.id,
                )
            )
        for posting in await self._market.private_postings(owner_id):
            options.append(
                TargetOptionView(
                    kind=TargetKind.PRIVATE_POSTING,
                    id=posting.id,
                    title=posting.title,
                    role_name=None,
                    role_id=None,
                    company_name=posting.company_name,
                    fit=posting_fit.get(posting.id),
                    salary=None,
                    source_kind=PASTED,
                    url=posting.url,
                    subscription_id=None,
                )
            )
        return options

    async def snapshot(self, owner_id: uuid.UUID, ref: TargetRef) -> TargetSnapshot:
        """Freeze the Target. For an unscored pasted JD this spends the user's key."""
        target_id = _uuid(ref)
        if ref.kind is TargetKind.PRIVATE_POSTING:
            posting = await self._market.private_posting(owner_id, target_id)
            fit = await self._assessment.fit_for_private_posting(owner_id, target_id)
            return await self._freeze(
                owner_id,
                ref,
                title=posting.title,
                company=posting.company_name,
                role=None,
                fit=fit,
                basis=RequirementBasis.POSTING,
            )

        role, title, company = await self._resolve_role(owner_id, ref, target_id)
        role_fit = next(
            (f for f in await self._assessment.fits(owner_id) if f.role_id == role.id), None
        )
        if role_fit is None:
            raise TargetUnusableError(
                f"{role.name} has not been scored against your profile yet; "
                "re-score fit on the role map first",
                role_id=str(role.id),
            )
        return await self._freeze(
            owner_id,
            ref,
            title=title,
            company=company,
            role=role,
            fit=role_fit,
            basis=RequirementBasis.ROLE,
        )

    async def preview(self, owner_id: uuid.UUID, ref: TargetRef) -> TargetPreview:
        """Everything needed to price work on a Target, spending nothing."""
        target_id = _uuid(ref)
        if ref.kind is not TargetKind.PRIVATE_POSTING:
            snapshot = await self.snapshot(owner_id, ref)
            return TargetPreview(
                label=snapshot.label,
                snapshot=snapshot,
                requirements_text=requirements_block(snapshot),
                pending_cost_usd=Decimal(0),
            )
        posting = await self._market.private_posting(owner_id, target_id)
        pending = await self._assessment.estimate_private_fit(owner_id, target_id)
        scored = await self.snapshot(owner_id, ref) if pending == 0 else None
        return TargetPreview(
            label=f"{posting.title} · {posting.company_name}",
            snapshot=scored,
            requirements_text=requirements_block(scored) if scored else posting.description,
            pending_cost_usd=pending,
        )

    async def _resolve_role(
        self, owner_id: uuid.UUID, ref: TargetRef, target_id: uuid.UUID
    ) -> tuple[RoleView, str, str]:
        if ref.kind is TargetKind.MATCHED_POSTING:
            for role, postings in await self._rolemap.role_postings(owner_id):
                for posting in postings:
                    if posting.id == target_id:
                        return role, posting.title, posting.company_name
            raise NotFoundError(
                "that opening is no longer in any of your roles", posting_id=str(target_id)
            )

        subscription = await self._market.subscription(owner_id, target_id)
        watched = _role_for(
            await self._rolemap.roles(owner_id), subscription.role_id, subscription.role_title
        )
        if watched is None:
            # A subscription is a Target whether or not a posting is open, but
            # its requirements come from the Role; with no Role there are none.
            raise TargetUnusableError(
                f"nothing is known yet about what {subscription.role_title or 'this role'} "
                f"at {subscription.company_name} requires; paste its job description instead",
                subscription_id=str(target_id),
            )
        return watched, subscription.role_title or watched.name, subscription.company_name

    async def _freeze(
        self,
        owner_id: uuid.UUID,
        ref: TargetRef,
        *,
        title: str,
        company: str,
        role: RoleView | None,
        fit: FitView,
        basis: RequirementBasis,
    ) -> TargetSnapshot:
        assessment = await self._assessment.latest(owner_id)
        names = {d.key: d.name for d in assessment.dimensions} if assessment else {}
        lifts = fit.lifts()
        requirements = fit.requirements or (role.requirements if role else ())
        try:
            return TargetSnapshot(
                ref=ref,
                title=title,
                company=company,
                role_id=str(role.id) if role else None,
                role_name=role.name if role else None,
                requirements=tuple(
                    Requirement(r.statement, r.weight, r.expected_level) for r in requirements
                ),
                basis=basis,
                fit_score=fit.score,
                dimensions=tuple(
                    DimensionGap(
                        dimension_key=g["dimension_key"],
                        name=names.get(g["dimension_key"], g["dimension_key"]),
                        user_score=g["user_score"],
                        target_score=g["target_score"],
                        lift=lifts.by_dimension.get(g["dimension_key"], 0),
                    )
                    for g in fit.gaps
                ),
                uncovered=tuple(
                    UncoveredGap(u["statement"], u["weight"], lift)
                    for u, lift in zip(fit.uncovered, lifts.by_uncovered, strict=True)
                ),
                requirement_map=dict(fit.requirement_map),
                taken_at=utcnow(),
            )
        except TargetError as exc:
            raise TargetUnusableError(str(exc), kind=str(ref.kind), id=ref.id) from exc


def requirements_block(snapshot: TargetSnapshot) -> str:
    return "\n".join(
        f"- {r.statement} (weight {r.weight}, expects {r.expected_level})"
        for r in snapshot.requirements
    )


def _role_for(roles: list[RoleView], role_id: uuid.UUID | None, title: str) -> RoleView | None:
    """The user's Role a subscription points at; by title once the id retires."""
    if role_id is not None:
        for role in roles:
            if role.id == role_id:
                return role
    wanted = title.casefold().strip()
    return next((role for role in roles if wanted and role.name.casefold() == wanted), None)


def _uuid(ref: TargetRef) -> uuid.UUID:
    try:
        return uuid.UUID(ref.id)
    except ValueError as exc:
        raise NotFoundError("target not found", kind=str(ref.kind), id=ref.id) from exc
