"""The Resume Advisor against a real database and object store, model stubbed.

What is worth proving: a résumé is written for a Target with every written line
cited and its requirement coverage decided by scores; invented evidence fails
the draft; a user's edit is theirs but cannot cite someone else's evidence; the
chat streams a proposal that becomes a version only when applied; an export is
a real PDF in object storage behind a signed link; and nobody else can read it.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal

import pytest
import pytest_asyncio

from kernel.ai_gateway import AiGateway
from kernel.ai_gateway.providers import REGISTRY, Completion, Request
from kernel.config import Settings
from kernel.db import Database
from kernel.errors import EvidenceNotOwnedError, NotFoundError
from kernel.storage import ObjectStore
from modules.assessment.public import AssessmentService
from modules.identity.public import IdentityService
from modules.market.public import MarketService
from modules.profile.public import ProfileService
from modules.resume.public import (
    Options,
    ResumeService,
    RevisionDone,
    RevisionFailed,
    RevisionText,
    Template,
)
from modules.rolemap.public import RoleMapService
from modules.target.public import TargetKind, TargetRef, TargetService

pytestmark = pytest.mark.integration

LEADS = "Lead technical direction across several teams"
RELIABILITY = "Own reliability: SLOs and incident reviews"
ORG = "Demonstrated org-level influence"


class StubProvider:
    """Completions and streams, each from what the test queued."""

    name = "anthropic"
    default_base_url = "https://llm.example.test"

    def __init__(self) -> None:
        self.replies: list[str] = []
        self.streams: list[list[str]] = []
        self.calls: list[Request] = []

    async def complete(self, client: object, request: Request) -> Completion:
        self.calls.append(request)
        return Completion(
            text=self.replies.pop(0) if self.replies else "{}",
            input_tokens=1000,
            output_tokens=500,
            model=request.model,
        )

    async def stream(self, client: object, request: Request) -> AsyncIterator[str]:
        self.calls.append(request)
        for chunk in self.streams.pop(0) if self.streams else []:
            yield chunk


@dataclass
class World:
    stub: StubProvider
    market: MarketService
    resume: ResumeService
    store: ObjectStore
    evidence_id: str


@pytest_asyncio.fixture
async def world(
    database: Database,
    settings: Settings,
    account: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> World:
    stub = StubProvider()
    monkeypatch.setitem(REGISTRY, "anthropic", stub)

    identity = IdentityService(database, default_monthly_cap_usd=Decimal("20"))
    await identity.set_credential(
        account, provider="anthropic", model="claude-opus-5", api_key="sk-test", base_url=None
    )
    store = ObjectStore(settings)
    # The api creates the bucket at startup, but this tier assumes only infra
    # that is up and migrated — on fresh infra nothing has created it yet.
    store.ensure_bucket()
    profile = ProfileService(
        database,
        object_store=store,
        connectors={},
        resume_max_bytes=settings.resume_max_bytes,
        resume_max_pages=settings.resume_max_pages,
        http_timeout_seconds=5,
        user_agent="test",
    )
    evidence = await profile.record_answer(
        account,
        question_id="q1",
        question="Who led the checkout migration?",
        answer="I led it across two teams",
    )
    gateway = AiGateway(settings=settings, credentials=identity, budget=identity)
    market = MarketService(database, manual_refresh_per_day=3)
    await market.add_market(account, f"Résumé market {uuid.uuid4().hex[:8]}")
    rolemap = RoleMapService(
        database,
        market=market,
        profile=profile,
        gateway=gateway,
        embedding_model=settings.embedding_model_name,
    )
    assessment = AssessmentService(
        database,
        profile=profile,
        rolemap=rolemap,
        market=market,
        gateway=gateway,
        confidence_threshold=settings.assessment_confidence_threshold,
    )
    target = TargetService(assessment=assessment, market=market, rolemap=rolemap)
    resume = ResumeService(
        database,
        target=target,
        profile=profile,
        assessment=assessment,
        gateway=gateway,
        object_store=store,
    )

    stub.replies.append(
        json.dumps(
            {
                "dimensions": [
                    {
                        "id": key,
                        "name": name,
                        "short_name": name,
                        "score": 70,
                        "confidence": 0.9,
                        "read": f"{name}, read from the evidence.",
                        "evidence_ids": [str(evidence.id)],
                    }
                    for key, name in [
                        ("leadership", "Technical leadership"),
                        ("reliability", "Reliability"),
                        ("craft", "Backend craft"),
                        ("delivery", "Delivery"),
                        ("mentoring", "Mentoring"),
                    ]
                ]
            }
        )
    )
    await assessment.run(account)
    return World(stub=stub, market=market, resume=resume, store=store, evidence_id=str(evidence.id))


def _score_the_jd(stub: StubProvider) -> None:
    stub.replies.append(
        json.dumps(
            {
                "requirements": [
                    {"statement": LEADS, "weight": 1.0, "expected_level": "expert"},
                    {"statement": RELIABILITY, "weight": 0.8, "expected_level": "advanced"},
                    {"statement": ORG, "weight": 0.5, "expected_level": "advanced"},
                ]
            }
        )
    )
    stub.replies.append(
        json.dumps(
            {
                "mappings": [
                    {"requirement_statement": LEADS, "dimension_id": "leadership"},
                    {"requirement_statement": RELIABILITY, "dimension_id": "reliability"},
                    {"requirement_statement": ORG, "dimension_id": None},
                ],
                "target_scores": [
                    {"dimension_id": "leadership", "target": 90},
                    {"dimension_id": "reliability", "target": 60},
                ],
                "reasoning": "Org influence has no evidence behind it at all.",
            }
        )
    )


def _resume_reply(evidence_id: str) -> str:
    return json.dumps(
        {
            "name": "Maya Lin Chen",
            "headline": "Staff Platform Engineer",
            "contact": "maya@example.com",
            "summary": "Leads platform work across teams.",
            "experience": [
                {
                    "title": "Backend Engineer",
                    "org": "Kestrel Financial",
                    "when": "2022 — now",
                    "bullets": [
                        {
                            "text": "Led the checkout migration across two teams",
                            "evidence_ids": [evidence_id],
                            "answers": LEADS,
                        }
                    ],
                }
            ],
            "skills": ["Go", "Postgres"],
        }
    )


async def _written(world: World, account: uuid.UUID) -> uuid.UUID:
    posting = await world.market.paste_job_description(
        account,
        company_name="Meridian Labs",
        title="Staff Platform Engineer",
        location=None,
        description="Set technical direction across three product teams...",
    )
    _score_the_jd(world.stub)
    world.stub.replies.append(_resume_reply(world.evidence_id))
    requested = await world.resume.request(
        account,
        TargetRef(TargetKind.PRIVATE_POSTING, str(posting.id)),
        template=Template.WARM,
        options=Options(),
    )
    await world.resume.generate(account, requested.id)
    return requested.id


async def test_a_resume_is_written_cited_with_coverage_decided_by_scores(
    world: World, account: uuid.UUID
) -> None:
    resume_id = await _written(world, account)

    view = await world.resume.get(account, resume_id)
    assert view.summary.status == "ready", view.summary.error_message
    assert view.version is not None
    assert (view.version.number, str(view.version.source)) == (1, "generated")
    assert view.content is not None
    [bullet] = view.content.experience[0].bullets
    assert bullet.evidence_ids == (world.evidence_id,)
    assert "I led it across two teams" in view.evidence[world.evidence_id].fact

    # 70 against 90 is 20 short: a gap. 70 against 60 clears it. Org influence
    # maps to nothing the user has, so there is nothing to cover it with.
    assert [(c.requirement, c.verdict) for c in view.coverage] == [
        (LEADS, "gap"),
        (RELIABILITY, "covered"),
        (ORG, "gap"),
    ]
    assert [e.id for e in view.coverage[1].evidence] == [world.evidence_id]


async def test_a_resume_citing_evidence_the_user_lacks_is_recorded_as_failed(
    world: World, account: uuid.UUID
) -> None:
    posting = await world.market.paste_job_description(
        account, company_name="Acme", title="Engineer", location=None, description="..."
    )
    _score_the_jd(world.stub)
    world.stub.replies.append(_resume_reply("00000000-0000-0000-0000-000000000000"))
    requested = await world.resume.request(
        account,
        TargetRef(TargetKind.PRIVATE_POSTING, str(posting.id)),
        template=Template.PLAIN,
        options=Options(),
    )
    await world.resume.generate(account, requested.id)

    view = await world.resume.get(account, requested.id)
    assert view.summary.status == "failed"
    assert view.summary.error_code == "evidence_not_owned"
    assert view.versions == ()


async def test_an_edit_is_the_users_own_but_cannot_cite_someone_elses_evidence(
    world: World, account: uuid.UUID
) -> None:
    resume_id = await _written(world, account)
    view = await world.resume.get(account, resume_id)
    assert view.content is not None
    edited = view.content.to_dict()
    edited["experience"][0]["bullets"][0]["text"] = "Led checkout's migration, end to end"

    saved = await world.resume.save_version(account, resume_id, content=edited)
    assert (saved.number, str(saved.source)) == (2, "manual")
    again = await world.resume.get(account, resume_id)
    assert again.content is not None
    assert str(again.content.experience[0].bullets[0].origin) == "yours"

    # Unchanged text is the same line: its stored citation stands, and an id
    # slipped in beside it is not what gets saved.
    stranger = str(uuid.uuid4())
    edited["experience"][0]["bullets"][0]["evidence_ids"] = [stranger]
    await world.resume.save_version(account, resume_id, content=edited)
    kept = await world.resume.get(account, resume_id)
    assert kept.content is not None
    assert stranger not in kept.content.cited()

    # A line the user rewrites keeps what they cite — which must be theirs.
    edited["experience"][0]["bullets"][0]["text"] = "Led the migration, start to finish"
    with pytest.raises(EvidenceNotOwnedError):
        await world.resume.save_version(account, resume_id, content=edited)


async def test_a_chat_proposal_streams_and_becomes_a_version_only_when_applied(
    world: World, account: uuid.UUID
) -> None:
    resume_id = await _written(world, account)
    view = await world.resume.get(account, resume_id)
    assert view.content is not None
    current = view.content.to_dict()
    proposed = json.loads(_resume_reply(world.evidence_id))
    proposed["summary"] = "Short."
    world.stub.streams.append(
        [
            "Shorter summary; ",
            "the lead line stays.\n<<<PRO",
            "POSAL>>>",
            json.dumps({"changed": True, "resume": proposed}),
        ]
    )

    events = [
        event
        async for event in world.resume.revise(
            account, resume_id, request="Make the summary shorter", content=current
        )
    ]

    text = "".join(e.text for e in events if isinstance(e, RevisionText))
    assert text == "Shorter summary; the lead line stays.\n"
    done = events[-1]
    assert isinstance(done, RevisionDone)
    assert done.proposal is not None and done.proposal.summary == "Short."
    assert len((await world.resume.get(account, resume_id)).versions) == 1

    applied = await world.resume.apply_revision(account, resume_id, done.revision_id)
    assert (applied.number, str(applied.source)) == (2, "chat")
    after = await world.resume.get(account, resume_id)
    assert after.content is not None and after.content.summary == "Short."
    assert after.revisions[0].applied_version_id == applied.id


async def test_a_proposal_with_an_uncited_new_line_is_rejected_in_the_stream(
    world: World, account: uuid.UUID
) -> None:
    resume_id = await _written(world, account)
    view = await world.resume.get(account, resume_id)
    assert view.content is not None
    proposed = json.loads(_resume_reply(world.evidence_id))
    proposed["experience"][0]["bullets"].append(
        {"text": "Promoted to Staff in 2024", "evidence_ids": []}
    )
    world.stub.streams.append(
        [
            "Added your promotion.",
            "<<<PROPOSAL>>>",
            json.dumps({"changed": True, "resume": proposed}),
        ]
    )

    events = [
        e
        async for e in world.resume.revise(
            account, resume_id, request="Add a promotion", content=view.content.to_dict()
        )
    ]

    assert isinstance(events[-1], RevisionFailed)
    assert events[-1].code == "ai_output_invalid"
    assert (await world.resume.get(account, resume_id)).revisions == ()


async def test_an_export_is_a_pdf_in_object_storage_behind_a_signed_link(
    world: World, account: uuid.UUID
) -> None:
    resume_id = await _written(world, account)
    export = await world.resume.request_export(account, resume_id, number=1)
    assert export.status == "rendering"

    await world.resume.export(account, export.id)

    ready = await world.resume.get_export(account, export.id)
    assert ready.status == "ready", ready.error_message
    assert ready.download_url is not None and "X-Amz-Signature" in ready.download_url
    key = f"users/{account}/exports/{export.id}.pdf"
    try:
        assert world.store.get(key).startswith(b"%PDF-")
    finally:
        world.store.delete(key)


async def test_another_user_cannot_read_the_resume_or_its_export(
    world: World, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    resume_id = await _written(world, account)
    export = await world.resume.request_export(account, resume_id, number=1)

    with pytest.raises(NotFoundError):
        await world.resume.get(other_account, resume_id)
    with pytest.raises(NotFoundError):
        await world.resume.get_export(other_account, export.id)
    assert await world.resume.saved(other_account) == []
