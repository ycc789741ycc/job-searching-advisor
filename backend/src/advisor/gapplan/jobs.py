"""Worker handlers for gap plans. These run on the ``ai`` queue."""

from __future__ import annotations

import uuid
from typing import Any

from kernel.logging import get_logger

log = get_logger(__name__)


async def draft(deps: Any, *, owner_id: str, plan_id: str) -> None:
    # A failure the plan can explain is recorded on it, not raised.
    await deps.gapplan.draft(uuid.UUID(owner_id), uuid.UUID(plan_id))
    log.info("gapplan.draft_finished", plan_id=plan_id)
