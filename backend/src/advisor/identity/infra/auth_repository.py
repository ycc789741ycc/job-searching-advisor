"""Repositories for the authentication tables."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from advisor.identity.infra.models import (
    Account,
    FederatedIdentity,
    PasswordCredential,
    RefreshToken,
)


def digest(token: str) -> str:
    """Refresh tokens are stored hashed.

    SHA-256 rather than Argon2 on purpose: the token is 32 random bytes, so
    there is no guessing to slow down — only a stored value to keep useless if
    the database leaks.
    """
    return hashlib.sha256(token.encode()).hexdigest()


class AuthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- accounts -----------------------------------------------------------

    async def account_by_email(self, email: str) -> Account | None:
        result = await self._session.execute(select(Account).where(Account.email == email))
        return result.scalar_one_or_none()

    # -- password credentials ----------------------------------------------

    async def credential_for(self, account_id: uuid.UUID) -> PasswordCredential | None:
        result = await self._session.execute(
            select(PasswordCredential).where(PasswordCredential.owner_id == account_id)
        )
        return result.scalar_one_or_none()

    def add_credential(self, credential: PasswordCredential) -> None:
        self._session.add(credential)

    async def delete_credential_for(self, account_id: uuid.UUID) -> int:
        result = await self._session.execute(
            delete(PasswordCredential).where(PasswordCredential.owner_id == account_id)
        )
        return int(getattr(result, "rowcount", 0) or 0)

    # -- federated identities ----------------------------------------------

    async def federated_identity(self, provider: str, subject: str) -> FederatedIdentity | None:
        result = await self._session.execute(
            select(FederatedIdentity).where(
                FederatedIdentity.provider == provider, FederatedIdentity.subject == subject
            )
        )
        return result.scalar_one_or_none()

    async def federated_identity_for(
        self, account_id: uuid.UUID, provider: str
    ) -> FederatedIdentity | None:
        result = await self._session.execute(
            select(FederatedIdentity).where(
                FederatedIdentity.owner_id == account_id, FederatedIdentity.provider == provider
            )
        )
        return result.scalar_one_or_none()

    def add_federated_identity(self, identity: FederatedIdentity) -> None:
        self._session.add(identity)

    # -- refresh tokens -----------------------------------------------------

    async def refresh_token(self, token: str) -> RefreshToken | None:
        result = await self._session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == digest(token))
        )
        return result.scalar_one_or_none()

    def add_refresh_token(self, token: RefreshToken) -> None:
        self._session.add(token)

    async def revoke_family(self, family_id: uuid.UUID, *, at: datetime) -> int:
        """Retire every token in a rotation chain.

        Used when a already-spent token is presented, which means either a
        replay or a theft — and we cannot tell which, so the chain goes.
        """
        result = await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=at)
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def revoke_all_for(self, account_id: uuid.UUID, *, at: datetime) -> int:
        result = await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.owner_id == account_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=at)
        )
        return int(getattr(result, "rowcount", 0) or 0)
