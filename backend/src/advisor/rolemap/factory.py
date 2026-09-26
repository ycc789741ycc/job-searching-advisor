"""Builds the role-map component from the infrastructure handles it is given.

The composition root calls this; nothing else constructs a repository or a
unit of work (ADR 0011).
"""

from __future__ import annotations

from advisor.market import MarketService
from advisor.profile import ProfileService
from advisor.rolemap.infra.unit_of_work import SqlAlchemyRoleMapUnitOfWork
from advisor.rolemap.service import RoleMapService
from kernel.ai_gateway import AiGateway
from kernel.db import Database


def create_rolemap_service(
    database: Database,
    *,
    market: MarketService,
    profile: ProfileService,
    gateway: AiGateway,
    embedding_model: str,
) -> RoleMapService:
    return RoleMapService(
        SqlAlchemyRoleMapUnitOfWork(database),
        market=market,
        profile=profile,
        gateway=gateway,
        embedding_model=embedding_model,
    )
