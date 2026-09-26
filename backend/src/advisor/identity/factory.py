"""Builds the identity component from the infrastructure handles it is given.

The composition root calls these; nothing else constructs a repository or a
unit of work (ADR 0011).
"""

from __future__ import annotations

from decimal import Decimal

from advisor.identity.auth import AuthService
from advisor.identity.infra.unit_of_work import SqlAlchemyIdentityUnitOfWork
from advisor.identity.service import IdentityService
from kernel.db import Database


def create_identity_service(
    database: Database, *, default_monthly_cap_usd: Decimal
) -> IdentityService:
    return IdentityService(
        SqlAlchemyIdentityUnitOfWork(database), default_monthly_cap_usd=default_monthly_cap_usd
    )


def create_auth_service(
    database: Database,
    *,
    secret: str,
    issuer: str,
    audience: str,
    access_ttl_seconds: int,
    refresh_ttl_days: int,
    default_monthly_cap_usd: Decimal,
) -> AuthService:
    return AuthService(
        SqlAlchemyIdentityUnitOfWork(database),
        secret=secret,
        issuer=issuer,
        audience=audience,
        access_ttl_seconds=access_ttl_seconds,
        refresh_ttl_days=refresh_ttl_days,
        default_monthly_cap_usd=default_monthly_cap_usd,
    )
