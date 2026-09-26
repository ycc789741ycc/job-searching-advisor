"""The boundaries from docs/technical_boundaries.md section 3, proven live.

These are the tests worth having: a privacy rule that is only enforced in
application code is one refactor away from being gone.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from kernel.db import Database
from wiring.models import OWNER_ZONE_TABLES

pytestmark = pytest.mark.integration


async def test_row_level_security_isolates_two_users(
    database: Database, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    """The core tenancy guarantee, enforced by Postgres and not by a WHERE."""
    async with database.for_user(account) as session:
        await session.execute(
            text(
                "INSERT INTO profile.evidence "
                "(id, owner_id, source, external_ref, reference, fact, confidence, "
                " created_at, updated_at) "
                "VALUES (:id, :owner, 'github', 'ref-1', 'GitHub · x', 'A fact', 0.9, "
                " now(), now())"
            ),
            {"id": uuid.uuid4(), "owner": account},
        )

    async with database.for_user(account) as session:
        mine = await session.execute(text("SELECT count(*) FROM profile.evidence"))
        assert mine.scalar_one() == 1

    async with database.for_user(other_account) as session:
        theirs = await session.execute(text("SELECT count(*) FROM profile.evidence"))
        assert theirs.scalar_one() == 0, "another user's evidence must not be visible"


async def test_a_query_without_app_user_id_sees_nothing_in_the_owner_zone(
    database: Database, account: uuid.UUID
) -> None:
    """Forgetting to scope a session returns no rows, never everyone's rows."""
    async with database.for_user(account) as session:
        await session.execute(
            text(
                "INSERT INTO profile.evidence "
                "(id, owner_id, source, external_ref, reference, fact, confidence, "
                " created_at, updated_at) "
                "VALUES (:id, :owner, 'github', 'ref-2', 'GitHub · x', 'A fact', 0.9, "
                " now(), now())"
            ),
            {"id": uuid.uuid4(), "owner": account},
        )

    async with database.shared() as session:
        leaked = await session.execute(text("SELECT count(*) FROM profile.evidence"))
        assert leaked.scalar_one() == 0


async def test_a_user_cannot_write_a_row_owned_by_someone_else(
    database: Database, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    """WITH CHECK stops a forged owner_id, not just a forged read."""
    with pytest.raises(Exception, match=r"row-level security|violates"):
        async with database.for_user(account) as session:
            await session.execute(
                text(
                    "INSERT INTO profile.evidence "
                    "(id, owner_id, source, external_ref, reference, fact, confidence, "
                    " created_at, updated_at) "
                    "VALUES (:id, :owner, 'github', 'forged', 'x', 'y', 0.5, now(), now())"
                ),
                {"id": uuid.uuid4(), "owner": other_account},
            )


async def test_every_owner_zone_table_actually_has_the_policy(database: Database) -> None:
    """A new table added without RLS is the failure mode this catches."""
    async with database.shared() as session:
        rows = await session.execute(
            text("SELECT schemaname || '.' || tablename FROM pg_tables WHERE rowsecurity IS TRUE")
        )
        protected = {row for row in rows.scalars()}
    missing = set(OWNER_ZONE_TABLES) - protected
    assert not missing, f"owner-zone tables without row-level security: {sorted(missing)}"


@pytest.mark.parametrize(
    "table",
    [
        "profile.evidence",
        "profile.source_connection",
        "identity.provider_credential",
        "market_user.private_job_posting",
        "assessment.skill_assessment",
        "rolemap.role",
        "gapplan.plan",
        "gapplan.task",
        "resume.resume",
        "resume.version",
    ],
)
async def test_the_crawler_role_cannot_touch_user_data(crawler_engine, table: str) -> None:
    """The crawler parses hostile HTML. It must not be able to reach a user row.

    market_user.private_job_posting is the one that matters most: pasted JDs
    are private by storage location, so the crawler cannot see them even by
    mistake.
    """
    async with crawler_engine.connect() as connection:
        with pytest.raises(Exception, match=r"permission denied|does not exist"):
            await connection.execute(text(f"SELECT count(*) FROM {table}"))


async def test_the_crawler_role_can_do_its_own_job(crawler_engine) -> None:
    async with crawler_engine.connect() as connection:
        for table in ("market.company", "market.job_posting", "market.crawl_source"):
            result = await connection.execute(text(f"SELECT count(*) FROM {table}"))
            assert result.scalar_one() >= 0


async def test_the_crawler_cannot_write_an_owner_scoped_outbox_event(crawler_engine) -> None:
    """It may emit market events, but it has no business naming a user."""
    async with crawler_engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT has_table_privilege('crawler_rw', 'outbox.event', 'INSERT'), "
                "       has_table_privilege('crawler_rw', 'outbox.event', 'UPDATE')"
            )
        )
        can_insert, can_update = result.one()
        assert can_insert, "the crawler emits PostingsChanged"
        assert not can_update, "only the dispatcher marks events dispatched"
