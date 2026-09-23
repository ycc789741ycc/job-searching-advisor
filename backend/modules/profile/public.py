"""The profile module's only importable surface.

Holds the CareerProfile: a career timeline plus every piece of Evidence for
one user. Facts only — a score never lives here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select

from domain.profile import (
    CitationError,
    EvidenceSource,
    assert_citations_exist,
    total_experience_months,
)
from domain.profile import (
    Position as PositionValue,
)
from kernel.crypto import decrypt, encrypt
from kernel.db import Database
from kernel.db.base import utcnow
from kernel.errors import NotFoundError, UpstreamFailedError, ValidationError
from kernel.fetch import GuardedClient
from kernel.logging import get_logger
from kernel.outbox import EventName, emit
from kernel.storage import ObjectStore, object_key
from modules.profile.infra.connectors import Connector, EvidenceDraft
from modules.profile.infra.models import (
    Evidence,
    Position,
    ProfileVersion,
    ResumeFile,
    SourceConnection,
)
from modules.profile.infra.resume_parser import ACCEPTED_TYPES, parse

__all__ = [
    "ACCEPTED_TYPES",
    "CitationError",
    "ConnectionView",
    "EvidenceSource",
    "EvidenceView",
    "ProfileService",
    "ProfileSnapshot",
    "ResumeFileView",
    "assert_citations_exist",
]

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ConnectionView:
    kind: str
    account: str | None
    status: str
    last_synced_at: datetime | None
    last_error: str | None


@dataclass(frozen=True, slots=True)
class EvidenceView:
    id: uuid.UUID
    source: EvidenceSource
    reference: str
    fact: str
    observed_on: date | None
    confidence: float


@dataclass(frozen=True, slots=True)
class ResumeFileView:
    id: uuid.UUID
    filename: str
    status: str
    parse_error: str | None
    uploaded_at: datetime


@dataclass(frozen=True, slots=True)
class ProfileSnapshot:
    """What the assessment reads. Facts and a version, never a score."""

    version: int
    evidence: tuple[EvidenceView, ...]
    positions: tuple[PositionValue, ...]
    total_experience_months: int


class ProfileService:
    def __init__(
        self,
        database: Database,
        *,
        object_store: ObjectStore,
        connectors: dict[str, Connector],
        resume_max_bytes: int,
        resume_max_pages: int,
        http_timeout_seconds: float,
        user_agent: str,
    ) -> None:
        self._db = database
        self._store = object_store
        self._connectors = connectors
        self._resume_max_bytes = resume_max_bytes
        self._resume_max_pages = resume_max_pages
        self._http_timeout = http_timeout_seconds
        self._user_agent = user_agent

    # -- connections --------------------------------------------------------

    async def connections(self, owner_id: uuid.UUID) -> list[ConnectionView]:
        async with self._db.for_user(owner_id) as session:
            rows = await session.execute(
                select(SourceConnection).where(SourceConnection.owner_id == owner_id)
            )
            return [_connection_view(row) for row in rows.scalars()]

    async def store_connection(
        self,
        owner_id: uuid.UUID,
        *,
        kind: str,
        access_token: str,
        refresh_token: str | None,
        scopes: tuple[str, ...],
        expires_at: datetime | None,
        account: str | None = None,
    ) -> ConnectionView:
        if kind not in self._connectors:
            raise ValidationError(f"unknown connector {kind!r}", kind=kind)

        async with self._db.for_user(owner_id) as session:
            rows = await session.execute(
                select(SourceConnection).where(
                    SourceConnection.owner_id == owner_id, SourceConnection.kind == kind
                )
            )
            connection = rows.scalar_one_or_none()
            if connection is None:
                connection = SourceConnection(owner_id=owner_id, kind=kind)
                session.add(connection)
            connection.encrypted_access_token = encrypt(access_token, context=str(owner_id))
            connection.encrypted_refresh_token = (
                encrypt(refresh_token, context=str(owner_id)) if refresh_token else None
            )
            connection.scopes = " ".join(scopes)
            connection.token_expires_at = expires_at
            connection.external_account = account
            connection.status = "connected"
            connection.last_error = None
            await session.flush()
            return _connection_view(connection)

    async def disconnect(self, owner_id: uuid.UUID, kind: str) -> None:
        async with self._db.for_user(owner_id) as session:
            rows = await session.execute(
                select(SourceConnection).where(
                    SourceConnection.owner_id == owner_id, SourceConnection.kind == kind
                )
            )
            connection = rows.scalar_one_or_none()
            if connection is not None:
                await session.delete(connection)

    async def sync_connection(self, owner_id: uuid.UUID, kind: str) -> int:
        """Fetch a source and turn it into Evidence. Worker `sync` queue only.

        This is the one place besides the AI gateway where a stored secret is
        opened, and the token never leaves this call.
        """
        connector = self._connectors.get(kind)
        if connector is None:
            raise ValidationError(f"unknown connector {kind!r}", kind=kind)

        async with self._db.for_user(owner_id) as session:
            rows = await session.execute(
                select(SourceConnection).where(
                    SourceConnection.owner_id == owner_id, SourceConnection.kind == kind
                )
            )
            connection = rows.scalar_one_or_none()
            if connection is None:
                raise NotFoundError(f"{kind} is not connected", kind=kind)
            token = decrypt(connection.encrypted_access_token, context=str(owner_id))
            connection_id = connection.id

        try:
            async with GuardedClient(
                timeout_seconds=self._http_timeout, user_agent=self._user_agent
            ) as client:
                drafts = await connector.fetch(client, token)
        except UpstreamFailedError as exc:
            async with self._db.for_user(owner_id) as session:
                failed = await session.get(SourceConnection, connection_id)
                if failed is not None:
                    failed.status = "failed"
                    failed.last_error = exc.message
            raise

        written = await self._write_evidence(
            owner_id,
            EvidenceSource(kind),
            drafts,
            source_connection_id=connection_id,
        )

        async with self._db.for_user(owner_id) as session:
            connection = await session.get(SourceConnection, connection_id)
            if connection is not None:
                connection.last_synced_at = utcnow()
                connection.status = "connected"
                connection.last_error = None
            await emit(
                session,
                EventName.SOURCE_SYNCED,
                {"kind": kind, "evidence": written},
                owner_id=owner_id,
            )
        return written

    # -- resume -------------------------------------------------------------

    async def upload_resume(
        self, owner_id: uuid.UUID, *, filename: str, content_type: str, content: bytes
    ) -> ResumeFileView:
        """Store the file and return. Parsing is a worker job, never inline."""
        if len(content) > self._resume_max_bytes:
            raise ValidationError(
                "this file is larger than we accept", limit_bytes=self._resume_max_bytes
            )
        if content_type not in ACCEPTED_TYPES:
            raise ValidationError(
                f"{content_type} is not a resume format we can read",
                content_type=content_type,
            )

        resume_id = uuid.uuid4()
        key = object_key(owner_id, "resumes", f"{resume_id}")
        self._store.put(key, content, content_type)

        async with self._db.for_user(owner_id) as session:
            resume = ResumeFile(
                id=resume_id,
                owner_id=owner_id,
                filename=filename,
                storage_key=key,
                content_type=content_type,
                byte_size=len(content),
                status="uploaded",
            )
            session.add(resume)
            await session.flush()
            return _resume_view(resume)

    async def parse_resume(self, owner_id: uuid.UUID, resume_id: uuid.UUID) -> int:
        """Worker `sync` queue. Parsing never happens in a request handler."""
        async with self._db.for_user(owner_id) as session:
            resume = await session.get(ResumeFile, resume_id)
            if resume is None or resume.owner_id != owner_id:
                raise NotFoundError("resume not found", resume_id=str(resume_id))
            key, content_type, filename = resume.storage_key, resume.content_type, resume.filename

        content = self._store.get(key)
        try:
            parsed = parse(
                content,
                content_type=content_type,
                filename=filename,
                max_pages=self._resume_max_pages,
            )
        except ValidationError as exc:
            async with self._db.for_user(owner_id) as session:
                resume = await session.get(ResumeFile, resume_id)
                if resume is not None:
                    resume.status = "failed"
                    resume.parse_error = exc.message
            raise

        written = await self._write_evidence(
            owner_id, EvidenceSource.RESUME, parsed.drafts, resume_file_id=resume_id
        )
        async with self._db.for_user(owner_id) as session:
            resume = await session.get(ResumeFile, resume_id)
            if resume is not None:
                resume.status = "parsed"
                resume.parsed_at = utcnow()
                resume.parse_error = None
        return written

    async def base_resume_text(self, owner_id: uuid.UUID, *, max_chars: int = 12_000) -> str | None:
        """The latest parsed résumé's text: what a new résumé revises, not replaces.

        Worker only — parsing never happens in a request handler. None when the
        user has not uploaded one that parsed.
        """
        async with self._db.for_user(owner_id) as session:
            latest = await session.execute(
                select(ResumeFile)
                .where(ResumeFile.owner_id == owner_id, ResumeFile.status == "parsed")
                .order_by(ResumeFile.parsed_at.desc())
                .limit(1)
            )
            resume = latest.scalar_one_or_none()
            if resume is None:
                return None
            key, content_type, filename = resume.storage_key, resume.content_type, resume.filename

        parsed = parse(
            self._store.get(key),
            content_type=content_type,
            filename=filename,
            max_pages=self._resume_max_pages,
        )
        return parsed.text[:max_chars]

    async def resumes(self, owner_id: uuid.UUID) -> list[ResumeFileView]:
        async with self._db.for_user(owner_id) as session:
            rows = await session.execute(select(ResumeFile).where(ResumeFile.owner_id == owner_id))
            return [_resume_view(row) for row in rows.scalars()]

    async def resume_download_url(self, owner_id: uuid.UUID, resume_id: uuid.UUID) -> str:
        async with self._db.for_user(owner_id) as session:
            resume = await session.get(ResumeFile, resume_id)
            if resume is None or resume.owner_id != owner_id:
                raise NotFoundError("resume not found", resume_id=str(resume_id))
            return self._store.signed_url(resume.storage_key)

    # -- answers ------------------------------------------------------------

    async def record_answer(
        self, owner_id: uuid.UUID, *, question_id: str, question: str, answer: str
    ) -> EvidenceView:
        """A reply to a follow-up question, stored as self-reported Evidence."""
        if not answer.strip():
            raise ValidationError("an answer is required")
        drafts = [
            EvidenceDraft(
                external_ref=f"answer:{question_id}",
                reference="Your answer",
                fact=f"{question} — {answer.strip()}",
                observed_on=utcnow().date(),
                confidence=0.7,
            )
        ]
        await self._write_evidence(owner_id, EvidenceSource.SELF_REPORTED, drafts)
        async with self._db.for_user(owner_id) as session:
            rows = await session.execute(
                select(Evidence).where(
                    Evidence.owner_id == owner_id,
                    Evidence.external_ref == f"answer:{question_id}",
                )
            )
            return _evidence_view(rows.scalar_one())

    # -- reading the profile ------------------------------------------------

    async def snapshot(self, owner_id: uuid.UUID) -> ProfileSnapshot:
        async with self._db.for_user(owner_id) as session:
            evidence_rows = await session.execute(
                select(Evidence).where(Evidence.owner_id == owner_id).order_by(Evidence.source)
            )
            position_rows = await session.execute(
                select(Position).where(Position.owner_id == owner_id)
            )
            version_row = await session.execute(
                select(ProfileVersion).where(ProfileVersion.owner_id == owner_id)
            )
            version = version_row.scalar_one_or_none()
            positions = tuple(
                PositionValue(
                    title=p.title, company=p.company, started_on=p.started_on, ended_on=p.ended_on
                )
                for p in position_rows.scalars()
            )
            return ProfileSnapshot(
                version=version.version if version is not None else 0,
                evidence=tuple(_evidence_view(e) for e in evidence_rows.scalars()),
                positions=positions,
                total_experience_months=total_experience_months(
                    list(positions), as_of=utcnow().date()
                ),
            )

    async def evidence_ids(self, owner_id: uuid.UUID) -> set[str]:
        """Used to reject AI output citing evidence this user does not have."""
        async with self._db.for_user(owner_id) as session:
            rows = await session.execute(select(Evidence.id).where(Evidence.owner_id == owner_id))
            return {str(row) for row in rows.scalars()}

    # -- internals ----------------------------------------------------------

    async def _write_evidence(
        self,
        owner_id: uuid.UUID,
        source: EvidenceSource,
        drafts: list[EvidenceDraft],
        *,
        source_connection_id: uuid.UUID | None = None,
        resume_file_id: uuid.UUID | None = None,
    ) -> int:
        """Upsert by ``external_ref`` so a re-sync updates rather than duplicates.

        Bumps the profile version and emits ``ProfileUpdated`` in the same
        transaction. Per domain section 2.9 this does not start an analysis —
        the user asks for that explicitly.
        """
        if not drafts:
            return 0

        async with self._db.for_user(owner_id) as session:
            existing_rows = await session.execute(
                select(Evidence).where(
                    Evidence.owner_id == owner_id,
                    Evidence.source == str(source),
                    Evidence.external_ref.in_([d.external_ref for d in drafts]),
                )
            )
            by_ref = {row.external_ref: row for row in existing_rows.scalars()}

            for draft in drafts:
                row = by_ref.get(draft.external_ref)
                if row is None:
                    session.add(
                        Evidence(
                            owner_id=owner_id,
                            source=str(source),
                            external_ref=draft.external_ref,
                            reference=draft.reference,
                            fact=draft.fact,
                            observed_on=draft.observed_on,
                            confidence=draft.confidence,
                            source_connection_id=source_connection_id,
                            resume_file_id=resume_file_id,
                        )
                    )
                else:
                    row.reference = draft.reference
                    row.fact = draft.fact
                    row.observed_on = draft.observed_on
                    row.confidence = draft.confidence

            version_rows = await session.execute(
                select(ProfileVersion).where(ProfileVersion.owner_id == owner_id)
            )
            version = version_rows.scalar_one_or_none()
            if version is None:
                version = ProfileVersion(owner_id=owner_id, version=1, updated_at=utcnow())
                session.add(version)
            else:
                version.version += 1
                version.updated_at = utcnow()
            await session.flush()

            await emit(
                session,
                EventName.PROFILE_UPDATED,
                {"source": str(source), "version": version.version, "count": len(drafts)},
                owner_id=owner_id,
            )
            return len(drafts)


def _connection_view(row: SourceConnection) -> ConnectionView:
    return ConnectionView(
        kind=row.kind,
        account=row.external_account,
        status=row.status,
        last_synced_at=row.last_synced_at,
        last_error=row.last_error,
    )


def _evidence_view(row: Evidence) -> EvidenceView:
    return EvidenceView(
        id=row.id,
        source=EvidenceSource(row.source),
        reference=row.reference,
        fact=row.fact,
        observed_on=row.observed_on,
        confidence=row.confidence,
    )


def _resume_view(row: ResumeFile) -> ResumeFileView:
    return ResumeFileView(
        id=row.id,
        filename=row.filename,
        status=row.status,
        parse_error=row.parse_error,
        uploaded_at=row.created_at,
    )
