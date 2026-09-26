"""The profile's other entities: connections, uploaded résumés, the career
timeline and the profile version. Evidence lives in ``evidence.py``.

Plain data with the rules that belong to it; ``advisor.profile.infra`` maps
these to and from the database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from advisor.profile.domain.timeline import Position


class ConnectionStatus(StrEnum):
    CONNECTED = "connected"
    FAILED = "failed"


@dataclass(slots=True)
class SourceConnection:
    """An authorised link to GitHub or Jira.

    The tokens are held encrypted; only the worker's ``sync`` queue opens them.
    """

    id: uuid.UUID
    owner_id: uuid.UUID
    kind: str
    external_account: str | None
    encrypted_access_token: str
    encrypted_refresh_token: str | None
    scopes: tuple[str, ...]
    status: ConnectionStatus
    last_error: str | None = None
    last_synced_at: datetime | None = None
    token_expires_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def new(cls, *, owner_id: uuid.UUID, kind: str) -> SourceConnection:
        return cls(
            id=uuid.uuid4(),
            owner_id=owner_id,
            kind=kind,
            external_account=None,
            encrypted_access_token="",
            encrypted_refresh_token=None,
            scopes=(),
            status=ConnectionStatus.CONNECTED,
        )

    def authorise(
        self,
        *,
        encrypted_access_token: str,
        encrypted_refresh_token: str | None,
        scopes: tuple[str, ...],
        expires_at: datetime | None,
        account: str | None,
    ) -> None:
        """New tokens clear any earlier failure."""
        self.encrypted_access_token = encrypted_access_token
        self.encrypted_refresh_token = encrypted_refresh_token
        self.scopes = scopes
        self.token_expires_at = expires_at
        self.external_account = account
        self.status = ConnectionStatus.CONNECTED
        self.last_error = None

    def sync_failed(self, error: str) -> None:
        self.status = ConnectionStatus.FAILED
        self.last_error = error

    def synced(self, at: datetime) -> None:
        self.last_synced_at = at
        self.status = ConnectionStatus.CONNECTED
        self.last_error = None


class ResumeStatus(StrEnum):
    UPLOADED = "uploaded"
    PARSED = "parsed"
    FAILED = "failed"


@dataclass(slots=True)
class ResumeFile:
    """An uploaded résumé: a source of evidence, and the base document a
    tailored résumé revises rather than replaces."""

    id: uuid.UUID
    owner_id: uuid.UUID
    filename: str
    storage_key: str
    content_type: str
    byte_size: int
    status: ResumeStatus
    parse_error: str | None = None
    parsed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def parsed(self, at: datetime) -> None:
        self.status = ResumeStatus.PARSED
        self.parsed_at = at
        self.parse_error = None

    def parse_failed(self, error: str) -> None:
        self.status = ResumeStatus.FAILED
        self.parse_error = error


@dataclass(slots=True)
class CareerPosition:
    """One position on the career timeline."""

    id: uuid.UUID
    owner_id: uuid.UUID
    title: str
    company: str
    started_on: date
    ended_on: date | None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def value(self) -> Position:
        return Position(
            title=self.title,
            company=self.company,
            started_on=self.started_on,
            ended_on=self.ended_on,
        )


@dataclass(slots=True)
class ProfileVersion:
    """Bumped whenever evidence changes, so a report computed from an older
    version can be detected as stale rather than shown as current."""

    id: uuid.UUID
    owner_id: uuid.UUID
    version: int
    updated_at: datetime

    @classmethod
    def first(cls, *, owner_id: uuid.UUID, at: datetime) -> ProfileVersion:
        return cls(id=uuid.uuid4(), owner_id=owner_id, version=1, updated_at=at)

    def bump(self, at: datetime) -> None:
        self.version += 1
        self.updated_at = at
