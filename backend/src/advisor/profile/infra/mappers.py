"""ORM rows to profile entities and back. No rules live here, only shape."""

from __future__ import annotations

from advisor.profile.domain import (
    CareerPosition,
    ConnectionStatus,
    Evidence,
    EvidenceSource,
    ProfileVersion,
    ResumeFile,
    ResumeStatus,
    SourceConnection,
)
from advisor.profile.infra import models

# --- source connection -----------------------------------------------------


def connection(row: models.SourceConnection) -> SourceConnection:
    return SourceConnection(
        id=row.id,
        owner_id=row.owner_id,
        kind=row.kind,
        external_account=row.external_account,
        encrypted_access_token=row.encrypted_access_token,
        encrypted_refresh_token=row.encrypted_refresh_token,
        scopes=tuple(row.scopes.split()),
        status=ConnectionStatus(row.status),
        last_error=row.last_error,
        last_synced_at=row.last_synced_at,
        token_expires_at=row.token_expires_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def connection_row(entity: SourceConnection) -> models.SourceConnection:
    row = models.SourceConnection(id=entity.id, owner_id=entity.owner_id, kind=entity.kind)
    apply_connection(row, entity)
    return row


def apply_connection(row: models.SourceConnection, entity: SourceConnection) -> None:
    row.external_account = entity.external_account
    row.encrypted_access_token = entity.encrypted_access_token
    row.encrypted_refresh_token = entity.encrypted_refresh_token
    row.scopes = " ".join(entity.scopes)
    row.status = str(entity.status)
    row.last_error = entity.last_error
    row.last_synced_at = entity.last_synced_at
    row.token_expires_at = entity.token_expires_at


# --- resume file -----------------------------------------------------------


def resume_file(row: models.ResumeFile) -> ResumeFile:
    return ResumeFile(
        id=row.id,
        owner_id=row.owner_id,
        filename=row.filename,
        storage_key=row.storage_key,
        content_type=row.content_type,
        byte_size=row.byte_size,
        status=ResumeStatus(row.status),
        parse_error=row.parse_error,
        parsed_at=row.parsed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def resume_file_row(entity: ResumeFile) -> models.ResumeFile:
    row = models.ResumeFile(
        id=entity.id,
        owner_id=entity.owner_id,
        filename=entity.filename,
        storage_key=entity.storage_key,
        content_type=entity.content_type,
        byte_size=entity.byte_size,
    )
    apply_resume_file(row, entity)
    return row


def apply_resume_file(row: models.ResumeFile, entity: ResumeFile) -> None:
    row.status = str(entity.status)
    row.parse_error = entity.parse_error
    row.parsed_at = entity.parsed_at


# --- evidence --------------------------------------------------------------


def evidence(row: models.Evidence) -> Evidence:
    return Evidence(
        id=row.id,
        owner_id=row.owner_id,
        source=EvidenceSource(row.source),
        external_ref=row.external_ref,
        reference=row.reference,
        fact=row.fact,
        observed_on=row.observed_on,
        confidence=row.confidence,
        source_connection_id=row.source_connection_id,
        resume_file_id=row.resume_file_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def evidence_row(entity: Evidence) -> models.Evidence:
    row = models.Evidence(
        id=entity.id,
        owner_id=entity.owner_id,
        source=str(entity.source),
        external_ref=entity.external_ref,
        source_connection_id=entity.source_connection_id,
        resume_file_id=entity.resume_file_id,
    )
    apply_evidence(row, entity)
    return row


def apply_evidence(row: models.Evidence, entity: Evidence) -> None:
    row.reference = entity.reference
    row.fact = entity.fact
    row.observed_on = entity.observed_on
    row.confidence = entity.confidence


# --- career timeline and version -------------------------------------------


def position(row: models.Position) -> CareerPosition:
    return CareerPosition(
        id=row.id,
        owner_id=row.owner_id,
        title=row.title,
        company=row.company,
        started_on=row.started_on,
        ended_on=row.ended_on,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def position_row(entity: CareerPosition) -> models.Position:
    row = models.Position(id=entity.id, owner_id=entity.owner_id)
    apply_position(row, entity)
    return row


def apply_position(row: models.Position, entity: CareerPosition) -> None:
    row.title = entity.title
    row.company = entity.company
    row.started_on = entity.started_on
    row.ended_on = entity.ended_on


def version(row: models.ProfileVersion) -> ProfileVersion:
    return ProfileVersion(
        id=row.id, owner_id=row.owner_id, version=row.version, updated_at=row.updated_at
    )


def version_row(entity: ProfileVersion) -> models.ProfileVersion:
    row = models.ProfileVersion(id=entity.id, owner_id=entity.owner_id)
    apply_version(row, entity)
    return row


def apply_version(row: models.ProfileVersion, entity: ProfileVersion) -> None:
    row.version = entity.version
    row.updated_at = entity.updated_at
