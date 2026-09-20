"""The ``worker`` deployable: queued jobs and the outbox dispatcher.

Phase 1 runs two queues in one process: ``ai`` (assessment, role naming,
requirement extraction, difficulty estimates, fits) and ``sync`` (connectors,
resume parsing). Splitting them is a deployment change, not a code change.
"""

from __future__ import annotations

import asyncio
import contextlib

from app.container import container
from app.dispatcher import dispatch_pending
from app.queue import queue
from kernel.config import get_settings
from kernel.jobs import Queue
from kernel.logging import configure_logging, get_logger

log = get_logger(__name__)

DISPATCH_INTERVAL_SECONDS = 2.0


async def _dispatch_loop() -> None:
    deps = container()
    while True:
        try:
            handled = await dispatch_pending(deps)
            if handled:
                log.info("outbox.dispatched", events=handled)
        except Exception:
            log.error("outbox.loop_error", exc_info=True)
        await asyncio.sleep(DISPATCH_INTERVAL_SECONDS)


async def main() -> None:
    settings = get_settings()
    configure_logging(f"{settings.service_name}-worker", settings.log_level)
    app = queue()

    async with app.open_async():
        dispatcher = asyncio.create_task(_dispatch_loop())
        log.info("worker.started", queues=[str(Queue.AI), str(Queue.SYNC)])
        try:
            await app.run_worker_async(queues=[str(Queue.AI), str(Queue.SYNC)])
        finally:
            dispatcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await dispatcher


if __name__ == "__main__":
    asyncio.run(main())
