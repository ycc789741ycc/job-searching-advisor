"""Worker handlers for the role map. These run on the ``ai`` queue."""

from __future__ import annotations

import uuid
from typing import Any

from kernel.logging import get_logger

log = get_logger(__name__)


async def recluster(deps: Any, *, owner_id: str) -> None:
    roles = await deps.rolemap.recluster(uuid.UUID(owner_id))
    log.info("rolemap.reclustered", roles=len(roles))
