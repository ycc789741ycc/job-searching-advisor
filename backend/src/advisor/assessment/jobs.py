"""Worker handlers for the assessment. These run on the ``ai`` queue."""

from __future__ import annotations

import uuid
from typing import Any

from kernel.logging import get_logger

log = get_logger(__name__)


async def run(deps: Any, *, owner_id: str) -> None:
    assessment = await deps.assessment.run(uuid.UUID(owner_id))
    log.info(
        "assessment.completed",
        dimensions=len(assessment.dimensions),
        model_id=assessment.model_id,
    )


async def compute_fits(deps: Any, *, owner_id: str) -> None:
    fits = await deps.assessment.compute_fits(uuid.UUID(owner_id))
    log.info("assessment.fits_computed", fits=len(fits))
