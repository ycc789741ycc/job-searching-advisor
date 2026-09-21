"""Repositories for the authentication tables."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.identity.infra.models import Account, PasswordCredential, RefreshToken


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
