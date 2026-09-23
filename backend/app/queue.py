"""Queue wiring.

Modules expose plain async functions in their ``jobs.py``; they are registered
as tasks here. That keeps Procrastinate out of the module boundary — a module
never imports the job runner, and swapping it is a change in this file only.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from procrastinate import App

from app.container import Container, container
from kernel.config import get_settings
from kernel.jobs import Queue, build_app
from kernel.logging import get_logger

log = get_logger(__name__)


@lru_cache(maxsize=1)
def queue() -> App:
    app = build_app(get_settings())
    _register(app)
    return app


async def enqueue(name: str, **kwargs: Any) -> None:
    """Defer a task by name, without importing the function that runs it."""
    await queue().configure_task(name=name).defer_async(**kwargs)


def _register(app: App) -> None:
    from modules.assessment import jobs as assessment_jobs
    from modules.gapplan import jobs as gapplan_jobs
    from modules.market import jobs as market_jobs
    from modules.profile import jobs as profile_jobs
    from modules.rolemap import jobs as rolemap_jobs

    def deps() -> Container:
        return container()

    @app.task(name="profile.sync_connection", queue=str(Queue.SYNC))
    async def sync_connection(owner_id: str, kind: str) -> None:
        await profile_jobs.sync_connection(deps(), owner_id=owner_id, kind=kind)

    @app.task(name="profile.parse_resume", queue=str(Queue.SYNC))
    async def parse_resume(owner_id: str, resume_id: str) -> None:
        await profile_jobs.parse_resume(deps(), owner_id=owner_id, resume_id=resume_id)

    @app.task(name="market.discover_board", queue=str(Queue.SYNC))
    async def discover_board(owner_id: str, company_id: str, company_name: str) -> None:
        await market_jobs.discover_board(
            deps(), owner_id=owner_id, company_id=company_id, company_name=company_name
        )

    @app.task(name="market.refresh_company", queue=str(Queue.SYNC))
    async def refresh_company(owner_id: str, company_id: str) -> None:
        await market_jobs.refresh_company(deps(), owner_id=owner_id, company_id=company_id)

    @app.task(name="market.materialize_crawl_sources", queue=str(Queue.SYNC))
    async def materialize_crawl_sources() -> None:
        await market_jobs.materialize_crawl_sources(deps())

    @app.task(name="rolemap.recluster", queue=str(Queue.AI))
    async def recluster(owner_id: str) -> None:
        await rolemap_jobs.recluster(deps(), owner_id=owner_id)

    @app.task(name="assessment.run", queue=str(Queue.AI))
    async def run_assessment(owner_id: str) -> None:
        await assessment_jobs.run(deps(), owner_id=owner_id)

    @app.task(name="assessment.compute_fits", queue=str(Queue.AI))
    async def compute_fits(owner_id: str) -> None:
        await assessment_jobs.compute_fits(deps(), owner_id=owner_id)

    @app.task(name="gapplan.draft", queue=str(Queue.AI))
    async def draft_plan(owner_id: str, plan_id: str) -> None:
        await gapplan_jobs.draft(deps(), owner_id=owner_id, plan_id=plan_id)
