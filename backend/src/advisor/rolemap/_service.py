"""The role map: postings grouped into roles, per user, on the user's key.

The split that matters here is who pays for what. Clustering runs locally on
the platform — plain computation. The user's key is spent only on naming a
cluster, pulling its requirements out, and estimating its interview difficulty
(domain decision 7).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from advisor.market import MarketService, PostingView, Visibility, band_from
from advisor.profile import ProfileService
from advisor.rolemap._domain import (
    DEFAULT_ROLE_COUNT,
    MIN_POSTINGS_FOR_A_ROLE,
    BarBasis,
    RoleChange,
    RoleCountError,
    blend,
    max_role_count,
    rank_by_fit,
    reconcile,
    validate_role_count,
)
from advisor.rolemap._infra.models import (
    Role,
    RoleLineage,
    RoleMapSetting,
    RoleMember,
    RoleRequirement,
)
from kernel.ai_gateway import AiGateway
from kernel.ai_gateway import load as load_template
from kernel.db import Database
from kernel.db.base import utcnow
from kernel.embeddings import cluster, embed
from kernel.errors import ValidationError
from kernel.logging import get_logger
from kernel.outbox import EventName, emit

__all__ = ["RequirementView", "RoleMapService", "RoleView"]

log = get_logger(__name__)

# The user's key is spent per cluster, so a first run has a predictable cost.
MAX_POSTINGS_IN_A_PROMPT = 12
MAX_DESCRIPTION_CHARS = 4000


class _Requirement(BaseModel):
    statement: str
    weight: float = Field(ge=0.0, le=1.0)
    expected_level: str


class _RoleExtraction(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    is_coherent: bool = True
    requirements: list[_Requirement] = Field(min_length=1, max_length=20)


class _DifficultyEstimate(BaseModel):
    difficulty: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


@dataclass(frozen=True, slots=True)
class _Group:
    """One cluster of postings, before it is analysed into a role."""

    keys: set[str]
    postings: list[PostingView]
    vectors: list[list[float]]


@dataclass(frozen=True, slots=True)
class RequirementView:
    statement: str
    weight: float
    expected_level: str


@dataclass(frozen=True, slots=True)
class RoleView:
    """One bubble. X is the hiring bar, Y is salary; size is fit, which lives
    in ``assessment`` because it is a property of the User x Role pair."""

    id: uuid.UUID
    name: str
    hiring_bar: int
    bar_basis: str
    bar_confidence: float
    bar_reasoning: str | None
    opening_count: int
    salary_bands: dict[str, Any]
    requirements: tuple[RequirementView, ...]
    is_coherent: bool


class RoleMapService:
    def __init__(
        self,
        database: Database,
        *,
        market: MarketService,
        profile: ProfileService,
        gateway: AiGateway,
        embedding_model: str,
    ) -> None:
        self._db = database
        self._market = market
        self._profile = profile
        self._gateway = gateway
        self._embedding_model = embedding_model

    async def roles(self, owner_id: uuid.UUID) -> list[RoleView]:
        async with self._db.for_user(owner_id) as session:
            role_rows = await session.execute(
                select(Role).where(Role.owner_id == owner_id, Role.retired_at.is_(None))
            )
            roles = list(role_rows.scalars())
            requirement_rows = await session.execute(
                select(RoleRequirement).where(RoleRequirement.owner_id == owner_id)
            )
            by_role: dict[uuid.UUID, list[RequirementView]] = {}
            for row in requirement_rows.scalars():
                by_role.setdefault(row.role_id, []).append(
                    RequirementView(row.statement, row.weight, row.expected_level)
                )
            return [_role_view(role, tuple(by_role.get(role.id, ()))) for role in roles]

    async def role_postings(self, owner_id: uuid.UUID) -> list[tuple[RoleView, list[PostingView]]]:
        """Each analysed role with the open postings grouped into it.

        Postings that have since expired, or left the user's scope, drop out:
        membership is resolved against the current scope, not stored copies.
        """
        roles = await self.roles(owner_id)
        if not roles:
            return []
        async with self._db.for_user(owner_id) as session:
            rows = await session.execute(
                select(RoleMember.role_id, RoleMember.posting_key).where(
                    RoleMember.owner_id == owner_id,
                    RoleMember.role_id.in_([role.id for role in roles]),
                )
            )
            keys_by_role: dict[uuid.UUID, list[str]] = {}
            for role_id, key in rows.all():
                keys_by_role.setdefault(role_id, []).append(key)

        in_scope = {_posting_key(p): p for p in await self._market.postings_in_scope(owner_id)}
        return [
            (role, [in_scope[key] for key in keys_by_role.get(role.id, []) if key in in_scope])
            for role in roles
        ]

    async def role_count(self, owner_id: uuid.UUID) -> int:
        """How many roles this user's role map analyses (ADR 0003)."""
        async with self._db.for_user(owner_id) as session:
            rows = await session.execute(
                select(RoleMapSetting.role_count).where(RoleMapSetting.owner_id == owner_id)
            )
            stored = rows.scalar_one_or_none()
        return DEFAULT_ROLE_COUNT if stored is None else stored

    async def set_role_count(self, owner_id: uuid.UUID, role_count: int) -> int:
        """Store the user's k. The caller has already shown the estimate for it
        and had it confirmed, so a change queues a recluster."""
        role_count = _checked(role_count)
        async with self._db.for_user(owner_id) as session:
            rows = await session.execute(
                select(RoleMapSetting).where(RoleMapSetting.owner_id == owner_id)
            )
            setting = rows.scalar_one_or_none()
            previous = DEFAULT_ROLE_COUNT if setting is None else setting.role_count
            if setting is None:
                session.add(RoleMapSetting(owner_id=owner_id, role_count=role_count))
            else:
                setting.role_count = role_count
            if role_count != previous:
                await emit(
                    session,
                    EventName.ROLE_COUNT_CHANGED,
                    {"from": previous, "to": role_count},
                    owner_id=owner_id,
                )
        log.info("rolemap.role_count_set", owner_id=str(owner_id), role_count=role_count)
        return role_count

    async def estimate_cost(
        self, owner_id: uuid.UUID, *, role_count: int | None = None
    ) -> dict[str, Any]:
        """The most a role map can cost, before any money is spent.

        A ceiling, not a prediction: the api runs no embeddings or clustering,
        so it prices the largest number of clusters these postings could form,
        capped at the user's k — or at a proposed k, so the price of changing it
        is shown before it is saved — each sent with the costliest prompt they
        could fill.
        """
        k = _checked(role_count) if role_count is not None else await self.role_count(owner_id)
        postings = await self._market.postings_in_scope(owner_id)
        max_clusters = max_role_count(len(postings), k)
        if max_clusters == 0:
            return {"max_clusters": 0, "role_count": k, "cost_usd": "0", "model_id": None}

        template = load_template("role_extraction", "v1")
        sample = _postings_block(sorted(postings, key=_prompt_length, reverse=True))
        estimate = await self._gateway.estimate(
            owner_id,
            task="rolemap.extract",
            template=template,
            inputs={"postings": sample},
            untrusted=frozenset({"postings"}),
        )
        # Two calls per cluster: extraction, then the difficulty estimate.
        total = estimate.cost_usd * max_clusters * 2
        return {
            "max_clusters": max_clusters,
            "role_count": k,
            "cost_usd": str(total.quantize(estimate.cost_usd)),
            "model_id": estimate.model_id,
            "rate_is_published": estimate.rate_is_published,
        }

    async def recluster(self, owner_id: uuid.UUID) -> list[RoleView]:
        """Rebuild this user's role map.

        Role ids survive: a goal or a saved fit pointing at a role must still
        find it after a crawl changes the underlying postings.
        """
        found = await self._group_postings(owner_id)
        if not found:
            log.info("rolemap.nothing_to_cluster", owner_id=str(owner_id))
            return []

        # Only the k clusters closest to the profile are analysed on the user's
        # key; the rest are left out, so roles they held are retired below.
        keep = rank_by_fit(
            await self._profile_vectors(owner_id),
            [group.vectors for group in found],
            limit=await self.role_count(owner_id),
        )
        groups = [found[index] for index in keep]
        log.info(
            "rolemap.selected",
            owner_id=str(owner_id),
            clusters_found=len(found),
            clusters_kept=len(groups),
        )

        previous = await self._previous_members(owner_id)
        reconciliation = reconcile(
            previous=previous,
            clusters=[group.keys for group in groups],
            new_id=lambda: str(uuid.uuid4()),
        )

        extraction_template = load_template("role_extraction", "v1")
        difficulty_template = load_template("difficulty_estimate", "v1")

        for index, group in enumerate(groups):
            role_id = uuid.UUID(reconciliation.assignments[index])
            # The same postings as the last analysis: nothing for the key to
            # redo. This is what makes lowering k free (ADR 0003).
            if previous.get(str(role_id)) == group.keys and await self._keep_role(
                owner_id, role_id=role_id, postings=group.postings
            ):
                continue
            block = _postings_block(group.postings)

            extracted = await self._gateway.run(
                owner_id,
                task="rolemap.extract",
                template=extraction_template,
                inputs={"postings": block},
                output_schema=_RoleExtraction,
                untrusted=frozenset({"postings"}),
            )

            requirements_block = "\n".join(
                f"- {r.statement} (weight {r.weight}, {r.expected_level})"
                for r in extracted.value.requirements
            )
            difficulty = await self._gateway.run(
                owner_id,
                task="rolemap.difficulty",
                template=difficulty_template,
                inputs={
                    "role_name": extracted.value.name,
                    "requirements": requirements_block,
                    "postings": block,
                },
                output_schema=_DifficultyEstimate,
                untrusted=frozenset({"postings"}),
            )

            # Phase 1 has no InterviewReports, so every bar is an estimate.
            bar = blend(
                estimated=difficulty.value.difficulty,
                estimate_confidence=difficulty.value.confidence,
                reported=None,
                reporter_count=0,
            )
            await self._store_role(
                owner_id,
                role_id=role_id,
                keys=group.keys,
                postings=group.postings,
                extraction=extracted.value,
                bar=bar,
                bar_reasoning=difficulty.value.reasoning,
                model_id=extracted.model_id,
                template_version=extracted.template_version,
            )

        await self._record_lineage(owner_id, reconciliation)
        return await self.roles(owner_id)

    # -- internals ----------------------------------------------------------

    async def _group_postings(self, owner_id: uuid.UUID) -> list[_Group]:
        """Cluster this user's postings locally. No AI, no cost."""
        scope = await self._market.scope_with_vectors(owner_id, self._embedding_model)
        if len(scope) < MIN_POSTINGS_FOR_A_ROLE:
            return []

        missing = [(key, posting) for key, posting, vector in scope if vector is None]
        if missing:
            texts = [
                "\n".join(
                    part for part in (p.title, p.title, p.location or "", p.description) if part
                )
                for _key, p in missing
            ]
            fresh = embed(texts, model_name=self._embedding_model)
            private = {
                p.id: vector
                for (_key, p), vector in zip(missing, fresh, strict=True)
                if p.visibility is Visibility.PRIVATE
            }
            if private:
                await self._market.store_private_vectors(owner_id, private)
            by_key = dict(zip((k for k, _ in missing), fresh, strict=True))
            scope = [
                (key, posting, vector if vector is not None else by_key[key])
                for key, posting, vector in scope
            ]

        keys = [key for key, _p, _v in scope]
        postings = [p for _k, p, _v in scope]
        vectors = [v for _k, _p, v in scope if v is not None]

        result = cluster(vectors, min_cluster_size=MIN_POSTINGS_FOR_A_ROLE)
        groups: list[_Group] = []
        for cluster_id in result.cluster_ids:
            members = result.members(cluster_id)
            groups.append(
                _Group(
                    keys={keys[i] for i in members},
                    postings=[postings[i] for i in members],
                    vectors=[vectors[i] for i in members],
                )
            )
        return groups

    async def _profile_vectors(self, owner_id: uuid.UUID) -> list[list[float]]:
        """The user's profile in the postings' embedding space: one vector per
        evidence fact and per position held. Local and platform-paid."""
        snapshot = await self._profile.snapshot(owner_id)
        texts = [e.fact for e in snapshot.evidence if e.fact.strip()]
        texts += [p.title for p in snapshot.positions if p.title.strip()]
        return embed(texts, model_name=self._embedding_model)

    async def _previous_members(self, owner_id: uuid.UUID) -> dict[str, set[str]]:
        async with self._db.for_user(owner_id) as session:
            rows = await session.execute(
                select(RoleMember.role_id, RoleMember.posting_key).where(
                    RoleMember.owner_id == owner_id
                )
            )
            previous: dict[str, set[str]] = {}
            for role_id, key in rows.all():
                previous.setdefault(str(role_id), set()).add(key)
            return previous

    async def _keep_role(
        self, owner_id: uuid.UUID, *, role_id: uuid.UUID, postings: list[PostingView]
    ) -> bool:
        """Keep an already-analysed role on the map, refreshing only what needs
        no AI: its opening count and salary bands. ``False`` means there is no
        analysed role to keep, and the cluster is analysed afresh."""
        bands = await self._salary_bands(owner_id, postings)
        async with self._db.for_user(owner_id) as session:
            role = await session.get(Role, role_id)
            if role is None:
                return False
            role.opening_count = len(postings)
            role.salary_bands = bands
            role.retired_at = None
        return True

    async def _store_role(
        self,
        owner_id: uuid.UUID,
        *,
        role_id: uuid.UUID,
        keys: set[str],
        postings: list[PostingView],
        extraction: _RoleExtraction,
        bar: Any,
        bar_reasoning: str,
        model_id: str,
        template_version: str,
    ) -> None:
        bands = await self._salary_bands(owner_id, postings)

        async with self._db.for_user(owner_id) as session:
            role = await session.get(Role, role_id)
            if role is None:
                role = Role(id=role_id, owner_id=owner_id, name=extraction.name)
                session.add(role)
            role.name = extraction.name
            role.is_coherent = extraction.is_coherent
            role.opening_count = len(postings)
            role.hiring_bar = bar.value
            role.bar_confidence = bar.confidence
            role.bar_basis = str(bar.basis)
            role.bar_sample_size = bar.sample_size
            role.bar_reasoning = bar_reasoning
            role.salary_bands = bands
            role.model_id = model_id
            role.template_version = template_version
            role.retired_at = None
            await session.flush()

            existing_members = await session.execute(
                select(RoleMember).where(RoleMember.role_id == role_id)
            )
            for member in existing_members.scalars():
                await session.delete(member)
            existing_requirements = await session.execute(
                select(RoleRequirement).where(RoleRequirement.role_id == role_id)
            )
            for requirement in existing_requirements.scalars():
                await session.delete(requirement)
            await session.flush()

            for key in sorted(keys):
                session.add(RoleMember(owner_id=owner_id, role_id=role_id, posting_key=key))
            for extracted in extraction.requirements:
                session.add(
                    RoleRequirement(
                        owner_id=owner_id,
                        role_id=role_id,
                        statement=extracted.statement,
                        weight=extracted.weight,
                        expected_level=extracted.expected_level,
                    )
                )

            await emit(
                session,
                EventName.ROLE_REQUIREMENTS_CHANGED,
                {"role_id": str(role_id), "requirements": len(extraction.requirements)},
                owner_id=owner_id,
            )

    async def _salary_bands(
        self, owner_id: uuid.UUID, postings: list[PostingView]
    ) -> dict[str, Any]:
        """One band per market the user selected, not one number per role."""
        selected = await self._market.markets(owner_id)
        bands: dict[str, Any] = {}
        for market in selected or [""]:
            ranges = [
                (p.salary.min_amount, p.salary.max_amount, p.salary.currency)
                for p in postings
                if p.salary is not None and (not market or (p.location or "") == market)
            ]
            band = band_from(ranges)
            if band is not None:
                bands[market or "all"] = {
                    "low": band.low,
                    "mid": band.mid,
                    "high": band.high,
                    "currency": band.currency,
                    "sample_size": band.sample_size,
                    # A thin market shows a low-confidence band rather than
                    # hiding the role.
                    "is_confident": band.is_confident,
                }
        return bands

    async def _record_lineage(self, owner_id: uuid.UUID, reconciliation: Any) -> None:
        async with self._db.for_user(owner_id) as session:
            for entry in reconciliation.lineage:
                session.add(
                    RoleLineage(
                        owner_id=owner_id,
                        role_id=uuid.UUID(entry.role_id),
                        kind=str(entry.kind),
                        from_role_ids=list(entry.from_role_ids),
                    )
                )
            for retired in reconciliation.retired_role_ids:
                role = await session.get(Role, uuid.UUID(retired))
                if role is not None:
                    role.retired_at = utcnow()

            split_or_merged = [
                e for e in reconciliation.lineage if e.kind in (RoleChange.SPLIT, RoleChange.MERGED)
            ]
            if split_or_merged:
                await emit(
                    session,
                    EventName.ROLE_SPLIT_OR_MERGED,
                    {
                        "changes": [
                            {
                                "kind": str(e.kind),
                                "role_id": e.role_id,
                                "from": list(e.from_role_ids),
                            }
                            for e in split_or_merged
                        ]
                    },
                    owner_id=owner_id,
                )
            await emit(
                session,
                EventName.ROLES_RECLUSTERED,
                {"roles": len(reconciliation.assignments)},
                owner_id=owner_id,
            )


def _posting_key(posting: PostingView) -> str:
    """The key a posting is clustered under (see ``MarketService.scope_with_vectors``)."""
    return f"private:{posting.id}" if posting.visibility is Visibility.PRIVATE else str(posting.id)


def _prompt_length(posting: PostingView) -> int:
    """How much of a prompt this posting fills, as ``_postings_block`` trims it."""
    return (
        len(posting.title)
        + len(posting.company_name)
        + len(posting.location or "")
        + min(len(posting.description), MAX_DESCRIPTION_CHARS)
    )


def _postings_block(postings: list[PostingView]) -> str:
    """Untrusted posting text, trimmed so one cluster is one predictable call."""
    chunks = []
    for posting in postings[:MAX_POSTINGS_IN_A_PROMPT]:
        chunks.append(
            f"### {posting.title} — {posting.company_name}"
            f" ({posting.location or 'location not stated'})\n"
            f"{posting.description[:MAX_DESCRIPTION_CHARS]}"
        )
    return "\n\n".join(chunks)


def _role_view(role: Role, requirements: tuple[RequirementView, ...]) -> RoleView:
    return RoleView(
        id=role.id,
        name=role.name,
        hiring_bar=role.hiring_bar,
        bar_basis=role.bar_basis,
        bar_confidence=role.bar_confidence,
        bar_reasoning=role.bar_reasoning,
        opening_count=role.opening_count,
        salary_bands=dict(role.salary_bands or {}),
        requirements=requirements,
        is_coherent=role.is_coherent,
    )


def role_bar_is_estimate(role: RoleView) -> bool:
    """Estimated bubbles are drawn with a dashed outline."""
    return role.bar_basis == str(BarBasis.ESTIMATED)


def _checked(role_count: int) -> int:
    try:
        return validate_role_count(role_count)
    except RoleCountError as exc:
        raise ValidationError(str(exc), role_count=role_count) from exc
