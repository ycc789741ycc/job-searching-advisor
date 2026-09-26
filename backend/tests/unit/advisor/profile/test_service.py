"""Profile use cases against in-memory storage: what they decide, with no database."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import pytest

from advisor.profile import EvidenceSource, ProfileService
from advisor.profile.domain import (
    CareerPosition,
    ConnectionStatus,
    ProfileUpdated,
    ResumeStatus,
    SourceSynced,
)
from advisor.profile.infra.connectors import EvidenceDraft
from kernel.crypto import decrypt
from kernel.errors import NotFoundError, UpstreamFailedError, ValidationError
from tests.unit.advisor.profile.fakes import FakeObjectStore, FakeProfileUnitOfWork

OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.UUID("00000000-0000-0000-0000-000000000002")

pytestmark = pytest.mark.usefixtures("clean_env")


class FakeConnector:
    def __init__(self, drafts: list[EvidenceDraft] | None = None, *, fails: bool = False) -> None:
        self.drafts = drafts or []
        self.fails = fails
        self.tokens: list[str] = []

    async def fetch(self, client: Any, token: str) -> list[EvidenceDraft]:
        self.tokens.append(token)
        if self.fails:
            raise UpstreamFailedError("GitHub said no")
        return self.drafts


def _draft(ref: str, fact: str = "Shipped the thing") -> EvidenceDraft:
    return EvidenceDraft(
        external_ref=ref,
        reference=f"https://github.test/{ref}",
        fact=fact,
        observed_on=date(2026, 9, 1),
        confidence=0.9,
    )


def _service(
    uow: FakeProfileUnitOfWork, *, connector: FakeConnector | None = None
) -> ProfileService:
    return ProfileService(
        uow,
        object_store=FakeObjectStore(),  # type: ignore[arg-type]
        connectors={"github": connector or FakeConnector()},  # type: ignore[dict-item]
        resume_max_bytes=10_000,
        resume_max_pages=5,
        http_timeout_seconds=1,
        user_agent="test",
    )


# --- connections -----------------------------------------------------------


async def test_a_connection_stores_its_tokens_encrypted_and_reconnects_in_place() -> None:
    uow = FakeProfileUnitOfWork()
    profile = _service(uow)

    await profile.store_connection(
        OWNER,
        kind="github",
        access_token="gho_first",
        refresh_token=None,
        scopes=("repo",),
        expires_at=None,
    )
    view = await profile.store_connection(
        OWNER,
        kind="github",
        access_token="gho_second",
        refresh_token="ghr_x",
        scopes=("repo", "read:org"),
        expires_at=None,
        account="octo",
    )

    (stored,) = uow.store.connections.values()
    assert "gho_second" not in stored.encrypted_access_token
    assert decrypt(stored.encrypted_access_token, context=str(OWNER)) == "gho_second"
    assert stored.scopes == ("repo", "read:org")
    assert view.account == "octo" and view.status == "connected"


async def test_an_unknown_connector_is_rejected() -> None:
    with pytest.raises(ValidationError):
        await _service(FakeProfileUnitOfWork()).store_connection(
            OWNER, kind="gitlab", access_token="t", refresh_token=None, scopes=(), expires_at=None
        )


async def test_a_sync_turns_a_source_into_evidence_and_bumps_the_version() -> None:
    uow = FakeProfileUnitOfWork()
    connector = FakeConnector([_draft("pr/1"), _draft("pr/2")])
    profile = _service(uow, connector=connector)
    await profile.store_connection(
        OWNER, kind="github", access_token="gho_x", refresh_token=None, scopes=(), expires_at=None
    )

    assert await profile.sync_connection(OWNER, "github") == 2

    assert connector.tokens == ["gho_x"]
    snapshot = await profile.snapshot(OWNER)
    assert snapshot.version == 1
    assert {e.reference for e in snapshot.evidence} == {
        "https://github.test/pr/1",
        "https://github.test/pr/2",
    }
    assert uow.store.events == [
        ProfileUpdated(owner_id=OWNER, source=EvidenceSource.GITHUB, version=1, count=2),
        SourceSynced(owner_id=OWNER, kind="github", evidence=2),
    ]
    (connection,) = uow.store.connections.values()
    assert connection.last_synced_at is not None


async def test_a_resync_restates_facts_rather_than_duplicating_them() -> None:
    uow = FakeProfileUnitOfWork()
    connector = FakeConnector([_draft("pr/1")])
    profile = _service(uow, connector=connector)
    await profile.store_connection(
        OWNER, kind="github", access_token="t", refresh_token=None, scopes=(), expires_at=None
    )
    await profile.sync_connection(OWNER, "github")

    connector.drafts = [_draft("pr/1", fact="Shipped the thing, twice")]
    await profile.sync_connection(OWNER, "github")

    snapshot = await profile.snapshot(OWNER)
    assert [e.fact for e in snapshot.evidence] == ["Shipped the thing, twice"]
    assert snapshot.version == 2


async def test_a_failed_sync_marks_the_connection_and_writes_nothing() -> None:
    uow = FakeProfileUnitOfWork()
    profile = _service(uow, connector=FakeConnector(fails=True))
    await profile.store_connection(
        OWNER, kind="github", access_token="t", refresh_token=None, scopes=(), expires_at=None
    )

    with pytest.raises(UpstreamFailedError):
        await profile.sync_connection(OWNER, "github")

    (connection,) = uow.store.connections.values()
    assert connection.status is ConnectionStatus.FAILED
    assert connection.last_error == "GitHub said no"
    assert uow.store.evidence == {} and uow.store.events == []


async def test_syncing_a_source_that_is_not_connected_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        await _service(FakeProfileUnitOfWork()).sync_connection(OWNER, "github")


async def test_disconnecting_twice_is_harmless() -> None:
    uow = FakeProfileUnitOfWork()
    profile = _service(uow)
    await profile.store_connection(
        OWNER, kind="github", access_token="t", refresh_token=None, scopes=(), expires_at=None
    )
    await profile.disconnect(OWNER, "github")
    await profile.disconnect(OWNER, "github")
    assert await profile.connections(OWNER) == []


# --- résumés ---------------------------------------------------------------

RESUME = (
    b"Jane Doe\n"
    b"- Led the migration of the billing platform to event sourcing\n"
    b"- Cut p99 checkout latency from 900ms to 180ms across three regions\n"
)


async def test_an_uploaded_resume_is_parsed_into_evidence_by_the_worker() -> None:
    uow = FakeProfileUnitOfWork()
    profile = _service(uow)

    uploaded = await profile.upload_resume(
        OWNER, filename="cv.txt", content_type="text/plain", content=RESUME
    )
    assert uploaded.status == "uploaded"
    assert await profile.base_resume_text(OWNER) is None

    written = await profile.parse_resume(OWNER, uploaded.id)

    assert written >= 2
    (stored,) = uow.store.resumes.values()
    assert stored.status is ResumeStatus.PARSED and stored.parsed_at is not None
    text = await profile.base_resume_text(OWNER)
    assert text is not None and "billing platform" in text


@pytest.mark.parametrize(
    ("content_type", "content"),
    [("image/png", b"x"), ("text/plain", b"x" * 20_000)],
)
async def test_a_resume_the_platform_cannot_take_is_refused_before_storing(
    content_type: str, content: bytes
) -> None:
    uow = FakeProfileUnitOfWork()
    with pytest.raises(ValidationError):
        await _service(uow).upload_resume(
            OWNER, filename="cv", content_type=content_type, content=content
        )
    assert uow.store.resumes == {}


async def test_another_users_resume_cannot_be_downloaded() -> None:
    uow = FakeProfileUnitOfWork()
    profile = _service(uow)
    theirs = await profile.upload_resume(
        OTHER, filename="cv.txt", content_type="text/plain", content=RESUME
    )
    with pytest.raises(NotFoundError):
        await profile.resume_download_url(OWNER, theirs.id)
    assert (await profile.resume_download_url(OTHER, theirs.id)).startswith("https://")


# --- answers and the snapshot ----------------------------------------------


async def test_an_answer_becomes_self_reported_evidence() -> None:
    uow = FakeProfileUnitOfWork()
    profile = _service(uow)

    evidence = await profile.record_answer(
        OWNER, question_id="q1", question="Led a team?", answer=" Yes, six people. "
    )

    assert evidence.source is EvidenceSource.SELF_REPORTED
    assert evidence.fact == "Led a team? — Yes, six people."
    assert await profile.evidence_ids(OWNER) == {str(evidence.id)}
    assert await profile.evidence_ids(OTHER) == set()


async def test_an_empty_answer_is_rejected() -> None:
    with pytest.raises(ValidationError):
        await _service(FakeProfileUnitOfWork()).record_answer(
            OWNER, question_id="q1", question="?", answer="  "
        )


async def test_the_snapshot_groups_evidence_by_source_and_totals_the_timeline() -> None:
    uow = FakeProfileUnitOfWork()
    profile = _service(uow, connector=FakeConnector([_draft("pr/1")]))
    await profile.store_connection(
        OWNER, kind="github", access_token="t", refresh_token=None, scopes=(), expires_at=None
    )
    await profile.record_answer(OWNER, question_id="q1", question="Q?", answer="A.")
    await profile.sync_connection(OWNER, "github")
    async with uow.for_owner(OWNER) as mine:
        await mine.positions.create(
            CareerPosition(
                id=uuid.uuid4(),
                owner_id=OWNER,
                title="Engineer",
                company="Acme",
                started_on=date(2020, 1, 1),
                ended_on=date(2022, 1, 1),
            )
        )

    snapshot = await profile.snapshot(OWNER)

    assert [e.source for e in snapshot.evidence] == [
        EvidenceSource.GITHUB,
        EvidenceSource.SELF_REPORTED,
    ]
    assert snapshot.version == 2
    assert snapshot.total_experience_months == 24
