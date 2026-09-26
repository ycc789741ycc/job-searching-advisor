"""The career profile.

Holds the CareerProfile: a career timeline plus every piece of Evidence for
one user. Facts only — a score never lives here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from advisor.profile.domain import (
    CareerPositionFilter,
    CitationError,
    Evidence,
    EvidenceFilter,
    EvidenceSource,
    OwnerProfile,
    ProfileUnitOfWork,
    ProfileUpdated,
    ProfileVersion,
    ProfileVersionFilter,
    ResumeFile,
    ResumeFileFilter,
    ResumeStatus,
    SourceConnection,
    SourceConnectionFilter,
    SourceSynced,
    assert_citations_exist,
    total_experience_months,
)
from advisor.profile.domain import (
    Position as PositionValue,
)
from advisor.profile.infra.connectors import Connector, EvidenceDraft
from advisor.profile.infra.resume_parser import ACCEPTED_TYPES, parse
from kernel.clock import utcnow
from kernel.crypto import decrypt, encrypt
from kernel.errors import NotFoundError, UpstreamFailedError, ValidationError
from kernel.fetch import GuardedClient
from kernel.logging import get_logger
from kernel.storage import ObjectStore, object_key

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
        uow: ProfileUnitOfWork,
        *,
        object_store: ObjectStore,
        connectors: dict[str, Connector],
        resume_max_bytes: int,
        resume_max_pages: int,
        http_timeout_seconds: float,
        user_agent: str,
    ) -> None:
        self._uow = uow
        self._store = object_store
        self._connectors = connectors
        self._resume_max_bytes = resume_max_bytes
        self._resume_max_pages = resume_max_pages
        self._http_timeout = http_timeout_seconds
        self._user_agent = user_agent

    # -- connections --------------------------------------------------------

    async def connections(self, owner_id: uuid.UUID) -> list[ConnectionView]:
        async with self._uow.for_owner(owner_id) as mine:
            found = await mine.connections.get_list(SourceConnectionFilter())
        return [_connection_view(c) for c in found]

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

        async with self._uow.for_owner(owner_id) as mine:
            existing = await _connection(mine, kind)
            connection = existing or SourceConnection.new(owner_id=owner_id, kind=kind)
            connection.authorise(
                encrypted_access_token=encrypt(access_token, context=str(owner_id)),
                encrypted_refresh_token=(
                    encrypt(refresh_token, context=str(owner_id)) if refresh_token else None
                ),
                scopes=scopes,
                expires_at=expires_at,
                account=account,
            )
            if existing is None:
                stored = await mine.connections.create(connection)
            else:
                stored = await mine.connections.update(connection)
            return _connection_view(stored)

    async def disconnect(self, owner_id: uuid.UUID, kind: str) -> None:
        async with self._uow.for_owner(owner_id) as mine:
            connection = await _connection(mine, kind)
            if connection is not None:
                await mine.connections.delete(connection.id)

    async def sync_connection(self, owner_id: uuid.UUID, kind: str) -> int:
        """Fetch a source and turn it into Evidence. Worker `sync` queue only.

        This is the one place besides the AI gateway where a stored secret is
        opened, and the token never leaves this call.
        """
        connector = self._connectors.get(kind)
        if connector is None:
            raise ValidationError(f"unknown connector {kind!r}", kind=kind)

        async with self._uow.for_owner(owner_id) as mine:
            connection = await _connection(mine, kind)
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
            async with self._uow.for_owner(owner_id) as mine:
                failed = await mine.connections.get(connection_id)
                if failed is not None:
                    failed.sync_failed(exc.message)
                    await mine.connections.update(failed)
            raise

        written = await self._write_evidence(
            owner_id,
            EvidenceSource(kind),
            drafts,
            source_connection_id=connection_id,
        )

        async with self._uow.for_owner(owner_id) as mine:
            synced = await mine.connections.get(connection_id)
            if synced is not None:
                synced.synced(utcnow())
                await mine.connections.update(synced)
            mine.record(SourceSynced(owner_id=owner_id, kind=kind, evidence=written))
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

        async with self._uow.for_owner(owner_id) as mine:
            stored = await mine.resumes.create(
                ResumeFile(
                    id=resume_id,
                    owner_id=owner_id,
                    filename=filename,
                    storage_key=key,
                    content_type=content_type,
                    byte_size=len(content),
                    status=ResumeStatus.UPLOADED,
                )
            )
        return _resume_view(stored)

    async def parse_resume(self, owner_id: uuid.UUID, resume_id: uuid.UUID) -> int:
        """Worker `sync` queue. Parsing never happens in a request handler."""
        async with self._uow.for_owner(owner_id) as mine:
            resume = await mine.resumes.get(resume_id)
            if resume is None:
                raise NotFoundError("resume not found", resume_id=str(resume_id))

        content = self._store.get(resume.storage_key)
        try:
            parsed = parse(
                content,
                content_type=resume.content_type,
                filename=resume.filename,
                max_pages=self._resume_max_pages,
            )
        except ValidationError as exc:
            async with self._uow.for_owner(owner_id) as mine:
                failed = await mine.resumes.get(resume_id)
                if failed is not None:
                    failed.parse_failed(exc.message)
                    await mine.resumes.update(failed)
            raise

        written = await self._write_evidence(
            owner_id, EvidenceSource.RESUME, parsed.drafts, resume_file_id=resume_id
        )
        async with self._uow.for_owner(owner_id) as mine:
            done = await mine.resumes.get(resume_id)
            if done is not None:
                done.parsed(utcnow())
                await mine.resumes.update(done)
        return written

    async def base_resume_text(self, owner_id: uuid.UUID, *, max_chars: int = 12_000) -> str | None:
        """The latest parsed résumé's text: what a new résumé revises, not replaces.

        Worker only — parsing never happens in a request handler. None when the
        user has not uploaded one that parsed.
        """
        async with self._uow.for_owner(owner_id) as mine:
            resume = await mine.resumes.get_latest_parsed()
        if resume is None:
            return None

        parsed = parse(
            self._store.get(resume.storage_key),
            content_type=resume.content_type,
            filename=resume.filename,
            max_pages=self._resume_max_pages,
        )
        return parsed.text[:max_chars]

    async def resumes(self, owner_id: uuid.UUID) -> list[ResumeFileView]:
        """Newest first. One user's uploads: a small set, read whole."""
        async with self._uow.for_owner(owner_id) as mine:
            uploaded = await mine.resumes.get_list(ResumeFileFilter())
        return [_resume_view(r) for r in uploaded]

    async def resume_download_url(self, owner_id: uuid.UUID, resume_id: uuid.UUID) -> str:
        async with self._uow.for_owner(owner_id) as mine:
            resume = await mine.resumes.get(resume_id)
        if resume is None:
            raise NotFoundError("resume not found", resume_id=str(resume_id))
        return self._store.signed_url(resume.storage_key)

    # -- answers ------------------------------------------------------------

    async def record_answer(
        self, owner_id: uuid.UUID, *, question_id: str, question: str, answer: str
    ) -> EvidenceView:
        """A reply to a follow-up question, stored as self-reported Evidence."""
        if not answer.strip():
            raise ValidationError("an answer is required")
        reference = f"answer:{question_id}"
        drafts = [
            EvidenceDraft(
                external_ref=reference,
                reference="Your answer",
                fact=f"{question} — {answer.strip()}",
                observed_on=utcnow().date(),
                confidence=0.7,
            )
        ]
        await self._write_evidence(owner_id, EvidenceSource.SELF_REPORTED, drafts)
        async with self._uow.for_owner(owner_id) as mine:
            stored = await mine.evidence.get_list(
                EvidenceFilter(source=EvidenceSource.SELF_REPORTED, external_refs=(reference,)),
                page_size=1,
            )
        if not stored:
            raise NotFoundError("the answer was not stored", question_id=question_id)
        return _evidence_view(stored[0])

    # -- reading the profile ------------------------------------------------

    async def snapshot(self, owner_id: uuid.UUID) -> ProfileSnapshot:
        """Every fact, grouped by source, with the timeline and the version.

        One user's profile: bounded by what they connected and uploaded, and
        read whole because the assessment reasons over all of it.
        """
        async with self._uow.for_owner(owner_id) as mine:
            evidence = await mine.evidence.get_list(EvidenceFilter())
            timeline = await mine.positions.get_list(CareerPositionFilter())
            versions = await mine.versions.get_list(ProfileVersionFilter(), page_size=1)
        positions = tuple(p.value for p in timeline)
        return ProfileSnapshot(
            version=versions[0].version if versions else 0,
            evidence=tuple(
                _evidence_view(e) for e in sorted(evidence, key=lambda e: str(e.source))
            ),
            positions=positions,
            total_experience_months=total_experience_months(list(positions), as_of=utcnow().date()),
        )

    async def evidence_ids(self, owner_id: uuid.UUID) -> set[str]:
        """Used to reject AI output citing evidence this user does not have."""
        async with self._uow.for_owner(owner_id) as mine:
            evidence = await mine.evidence.get_list(EvidenceFilter())
        return {str(e.id) for e in evidence}

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

        Bumps the profile version and records ``ProfileUpdated`` in the same
        transaction. Per domain section 2.9 this does not start an analysis —
        the user asks for that explicitly.
        """
        if not drafts:
            return 0

        async with self._uow.for_owner(owner_id) as mine:
            existing = await mine.evidence.get_list(
                EvidenceFilter(source=source, external_refs=tuple(d.external_ref for d in drafts))
            )
            by_ref = {e.external_ref: e for e in existing}

            for draft in drafts:
                known = by_ref.get(draft.external_ref)
                if known is None:
                    await mine.evidence.create(
                        Evidence.cited(
                            owner_id=owner_id,
                            source=source,
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
                    known.restate(
                        reference=draft.reference,
                        fact=draft.fact,
                        observed_on=draft.observed_on,
                        confidence=draft.confidence,
                    )
                    await mine.evidence.update(known)

            now = utcnow()
            versions = await mine.versions.get_list(ProfileVersionFilter(), page_size=1)
            if versions:
                version = versions[0]
                version.bump(now)
                version = await mine.versions.update(version)
            else:
                version = await mine.versions.create(
                    ProfileVersion.first(owner_id=owner_id, at=now)
                )

            mine.record(
                ProfileUpdated(
                    owner_id=owner_id, source=source, version=version.version, count=len(drafts)
                )
            )
            return len(drafts)


async def _connection(mine: OwnerProfile, kind: str) -> SourceConnection | None:
    found = await mine.connections.get_list(SourceConnectionFilter(kind=kind), page_size=1)
    return found[0] if found else None


def _connection_view(connection: SourceConnection) -> ConnectionView:
    return ConnectionView(
        kind=connection.kind,
        account=connection.external_account,
        status=str(connection.status),
        last_synced_at=connection.last_synced_at,
        last_error=connection.last_error,
    )


def _evidence_view(evidence: Evidence) -> EvidenceView:
    return EvidenceView(
        id=evidence.id,
        source=evidence.source,
        reference=evidence.reference,
        fact=evidence.fact,
        observed_on=evidence.observed_on,
        confidence=evidence.confidence,
    )


def _resume_view(resume: ResumeFile) -> ResumeFileView:
    # Set by the database when the upload was stored; always present on a read.
    assert resume.created_at is not None, "a stored resume has an upload time"
    return ResumeFileView(
        id=resume.id,
        filename=resume.filename,
        status=str(resume.status),
        parse_error=resume.parse_error,
        uploaded_at=resume.created_at,
    )
