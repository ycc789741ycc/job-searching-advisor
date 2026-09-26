"""The role map's "Top matched" list, against a real database.

What is worth proving: expired postings, retired roles and pasted JDs stay
out; the order follows the role's fit; and a row knows when the user already
watches that role at that company.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text

from advisor.assessment import AssessmentService, FitView
from advisor.identity import create_identity_service
from advisor.market import (
    NormalizedPosting,
    SourceKind,
    create_crawl_ingest,
    create_market_service,
)
from advisor.market.infra.models import CrawlSource
from advisor.profile import create_profile_service
from advisor.rolemap import RoleMapService
from advisor.rolemap.infra.models import Role, RoleMember
from kernel.ai_gateway import AiGateway
from kernel.config import Settings
from kernel.db import Database
from kernel.db.base import utcnow
from kernel.storage import ObjectStore

pytestmark = pytest.mark.integration


def _posting(title: str, company: str, market: str) -> NormalizedPosting:
    return NormalizedPosting(
        external_id=title,
        company_name=company,
        title=title,
        location=market,
        description=f"You will work on {title}.",
        url=f"https://boards.test/{title}",
        source_kind=SourceKind.ATS_BOARD,
        posted_on=date(2026, 9, 1),
        salary=None,
    )


def _fit(role_id: uuid.UUID, score: int) -> FitView:
    return FitView(
        role_id=role_id,
        private_posting_id=None,
        score=score,
        reasoning="",
        gaps=(),
        uncovered=(),
        model_id="stub",
        created_at=utcnow(),
    )


async def test_top_matched_lists_open_postings_in_live_roles_by_role_fit(
    database: Database,
    crawler_database: Database,
    settings: Settings,
    account: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tag = uuid.uuid4().hex[:8]
    market_name = f"Match market {tag}"
    northwind, kestrel = f"Northwind {tag}", f"Kestrel {tag}"

    async with crawler_database.shared() as session:
        row = CrawlSource(kind="greenhouse", endpoint=f"https://boards.test/{uuid.uuid4()}")
        session.add(row)
        await session.flush()
        source_id = row.id

    try:
        ingest = create_crawl_ingest(crawler_database)
        await ingest.record_crawl(
            source_id,
            [
                _posting(f"Backend A {tag}", northwind, market_name),
                _posting(f"Backend B {tag}", kestrel, market_name),
                _posting(f"Backend Gone {tag}", kestrel, market_name),
                _posting(f"Platform {tag}", kestrel, market_name),
                _posting(f"Retired {tag}", northwind, market_name),
            ],
        )
        # A later crawl no longer sees one of them: it expires.
        await ingest.record_crawl(
            source_id,
            [
                _posting(f"Backend A {tag}", northwind, market_name),
                _posting(f"Backend B {tag}", kestrel, market_name),
                _posting(f"Platform {tag}", kestrel, market_name),
                _posting(f"Retired {tag}", northwind, market_name),
            ],
        )
        async with database.shared() as session:
            found = await session.execute(
                text("SELECT title, id FROM market.job_posting WHERE crawl_source_id = :id"),
                {"id": source_id},
            )
            ids: dict[str, uuid.UUID] = {title: posting_id for title, posting_id in found.all()}

        market = create_market_service(database, manual_refresh_per_day=3)
        await market.add_market(account, market_name)
        pasted = await market.paste_job_description(
            account,
            company_name=northwind,
            title=f"My own JD {tag}",
            location=market_name,
            description="Pasted by the user.",
        )

        backend, platform, retired = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        async with database.for_user(account) as session:
            session.add_all(
                [
                    Role(id=backend, owner_id=account, name="Senior Backend Engineer"),
                    Role(id=platform, owner_id=account, name="Staff Platform Engineer"),
                    Role(id=retired, owner_id=account, name="Old Role", retired_at=utcnow()),
                ]
            )
            await session.flush()
            members = [
                (backend, str(ids[f"Backend A {tag}"])),
                (backend, str(ids[f"Backend B {tag}"])),
                (backend, str(ids[f"Backend Gone {tag}"])),
                (backend, f"private:{pasted.id}"),
                (platform, str(ids[f"Platform {tag}"])),
                (retired, str(ids[f"Retired {tag}"])),
            ]
            session.add_all(
                RoleMember(owner_id=account, role_id=role_id, posting_key=key)
                for role_id, key in members
            )

        watched = await market.subscribe(
            account, company_name=northwind, role_title="senior backend engineer"
        )

        identity = create_identity_service(database, default_monthly_cap_usd=Decimal("20"))
        profile = create_profile_service(
            database,
            object_store=ObjectStore(settings),
            connectors={},
            resume_max_bytes=settings.resume_max_bytes,
            resume_max_pages=settings.resume_max_pages,
            http_timeout_seconds=5,
            user_agent="test",
        )
        gateway = AiGateway(settings=settings, credentials=identity, budget=identity)
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

        async def fits(owner_id: uuid.UUID) -> list[FitView]:
            return [_fit(backend, 80), _fit(platform, 91), _fit(retired, 99)]

        monkeypatch.setattr(assessment, "fits", fits)

        matched = await assessment.matched_postings(account, limit=10)

        # Equal fits break by company: Kestrel before Northwind.
        assert [(m.title, m.fit) for m in matched] == [
            (f"Platform {tag}", 91),
            (f"Backend B {tag}", 80),
            (f"Backend A {tag}", 80),
        ]
        by_title = {m.title: m for m in matched}
        assert by_title[f"Backend A {tag}"].subscription_id == watched.id
        assert by_title[f"Backend B {tag}"].subscription_id is None
        assert by_title[f"Platform {tag}"].subscription_id is None

        assert [m.title for m in await assessment.matched_postings(account, limit=1)] == [
            f"Platform {tag}"
        ]
    finally:
        async with crawler_database.shared() as session:
            await session.execute(
                text("DELETE FROM market.job_posting WHERE crawl_source_id = :id"),
                {"id": source_id},
            )
            await session.execute(
                text("DELETE FROM market.crawl_source WHERE id = :id"), {"id": source_id}
            )
