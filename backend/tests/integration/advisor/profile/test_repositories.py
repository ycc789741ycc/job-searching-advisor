"""The SQLAlchemy side of the profile's repositories, against a real database.

Worth proving here: every entity survives its mapper, an owner scope sees
nobody else's rows, "latest parsed" orders by parsing and not by upload, and
each event lands in the outbox as the dispatcher reads it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text

from advisor.profile.domain import (
    CareerPosition,
    CareerPositionFilter,
    Evidence,
    EvidenceFilter,
    EvidenceSource,
    ProfileUpdated,
    ProfileVersion,
    ProfileVersionFilter,
    ResumeFile,
    ResumeFileFilter,
    ResumeStatus,
    SourceConnection,
    SourceConnectionFilter,
    SourceSynced,
)
from advisor.profile.infra.unit_of_work import SqlAlchemyProfileUnitOfWork
from kernel.db import Database
from kernel.errors import NotFoundError

pytestmark = pytest.mark.integration


def _resume(owner_id: uuid.UUID, name: str) -> ResumeFile:
    return ResumeFile(
        id=uuid.uuid4(),
        owner_id=owner_id,
        filename=name,
        storage_key=f"{owner_id}/resumes/{name}",
        content_type="text/plain",
        byte_size=10,
        status=ResumeStatus.UPLOADED,
    )


async def test_profile_entities_round_trip_and_stay_with_their_owner(
    database: Database, account: uuid.UUID, other_account: uuid.UUID
) -> None:
    uow = SqlAlchemyProfileUnitOfWork(database)
    at = datetime(2026, 9, 27, tzinfo=UTC)

    async with uow.for_owner(account) as mine:
        connection = SourceConnection.new(owner_id=account, kind="github")
        connection.authorise(
            encrypted_access_token="ciphertext",
            encrypted_refresh_token=None,
            scopes=("repo", "read:org"),
            expires_at=None,
            account="octo",
        )
        connection = await mine.connections.create(connection)
        evidence = await mine.evidence.create(
            Evidence.cited(
                owner_id=account,
                source=EvidenceSource.GITHUB,
                external_ref="pr/1",
                reference="https://github.test/pr/1",
                fact="Shipped",
                observed_on=date(2026, 9, 1),
                confidence=0.9,
                source_connection_id=connection.id,
            )
        )
        position = await mine.positions.create(
            CareerPosition(
                id=uuid.uuid4(),
                owner_id=account,
                title="Engineer",
                company="Acme",
                started_on=date(2020, 1, 1),
                ended_on=None,
            )
        )
        version = await mine.versions.create(ProfileVersion.first(owner_id=account, at=at))

    async with uow.for_owner(account) as mine:
        assert await mine.connections.get_list(SourceConnectionFilter(kind="github")) == [
            connection
        ]
        assert await mine.evidence.get_list(
            EvidenceFilter(source=EvidenceSource.GITHUB, external_refs=("pr/1",))
        ) == [evidence]
        assert await mine.positions.get_list(CareerPositionFilter()) == [position]
        version.bump(at)
        bumped = await mine.versions.update(version)
        assert bumped.version == 2

    async with uow.for_owner(other_account) as theirs:
        assert await theirs.evidence.get(evidence.id) is None
        assert await theirs.versions.get_count(ProfileVersionFilter()) == 0
        with pytest.raises(NotFoundError):
            await theirs.connections.delete(connection.id)


async def test_the_latest_parsed_resume_is_the_one_parsed_last(
    database: Database, account: uuid.UUID
) -> None:
    uow = SqlAlchemyProfileUnitOfWork(database)
    async with uow.for_owner(account) as mine:
        older = await mine.resumes.create(_resume(account, "older.txt"))
    async with uow.for_owner(account) as mine:
        newer = await mine.resumes.create(_resume(account, "newer.txt"))

    async with uow.for_owner(account) as mine:
        assert await mine.resumes.get_latest_parsed() is None
        newer.parsed(datetime(2026, 9, 1, tzinfo=UTC))
        await mine.resumes.update(newer)
        # Uploaded first, parsed last: it is the latest parsed.
        older.parsed(datetime(2026, 9, 2, tzinfo=UTC))
        await mine.resumes.update(older)

    async with uow.for_owner(account) as mine:
        latest = await mine.resumes.get_latest_parsed()
        assert latest is not None and latest.id == older.id
        assert [r.id for r in await mine.resumes.get_list(ResumeFileFilter())] == [
            newer.id,
            older.id,
        ]


async def test_profile_events_reach_the_outbox_as_the_dispatcher_reads_them(
    database: Database, account: uuid.UUID
) -> None:
    uow = SqlAlchemyProfileUnitOfWork(database)
    async with uow.for_owner(account) as mine:
        mine.record(SourceSynced(owner_id=account, kind="github", evidence=3))
        mine.record(
            ProfileUpdated(owner_id=account, source=EvidenceSource.GITHUB, version=4, count=3)
        )

    async with database.shared() as session:
        rows = await session.execute(
            text("SELECT name, payload FROM outbox.event WHERE owner_id = :owner"),
            {"owner": account},
        )
        assert sorted(rows.all()) == [
            ("ProfileUpdated", {"source": "github", "version": 4, "count": 3}),
            ("SourceSynced", {"kind": "github", "evidence": 3}),
        ]
