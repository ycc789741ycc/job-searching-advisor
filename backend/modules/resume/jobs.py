"""Worker handlers for the Resume Advisor.

Writing runs on the ``ai`` queue; PDF export on ``docs``. A failure the
résumé or export can explain is recorded on it, not raised.
"""

from __future__ import annotations

import uuid
from typing import Any

from kernel.logging import get_logger

log = get_logger(__name__)


async def generate(deps: Any, *, owner_id: str, resume_id: str) -> None:
    await deps.resume.generate(uuid.UUID(owner_id), uuid.UUID(resume_id))
    log.info("resume.generate_finished", resume_id=resume_id)


async def export(deps: Any, *, owner_id: str, export_id: str) -> None:
    await deps.resume.export(uuid.UUID(owner_id), uuid.UUID(export_id))
    log.info("resume.export_finished", export_id=export_id)
