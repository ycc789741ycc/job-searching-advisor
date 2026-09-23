"""The ``api`` deployable: HTTP, SSE and nothing else.

No business rules live here — routers map HTTP onto module services. Uploaded
documents are stored and queued, never parsed in a request handler.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import errors
from app.container import container
from app.queue import queue
from kernel.config import Unit, get_settings
from kernel.logging import configure_logging, get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.service_name, settings.log_level)
    deps = container()
    # Missing configuration fails here, at startup, not at first use.
    settings.require_for(Unit.API)
    deps.object_store.ensure_bucket()
    async with queue().open_async():
        log.info("api.started", app_env=settings.app_env, port=settings.port)
        yield
    await deps.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="Job Searching Advisor",
        version="0.1.0",
        lifespan=lifespan,
    )

    # The SPA is the only browser client, and it is served from its own origin.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    errors.install(application)

    from modules.assessment.api import router as assessment_router
    from modules.gapplan.api import router as gapplan_router
    from modules.identity.api import router as identity_router
    from modules.market.api import router as market_router
    from modules.profile.api import router as profile_router
    from modules.resume.api import router as resume_router
    from modules.rolemap.api import router as rolemap_router
    from modules.target.api import router as target_router

    for router in (
        identity_router,
        profile_router,
        market_router,
        rolemap_router,
        assessment_router,
        target_router,
        gapplan_router,
        resume_router,
    ):
        application.include_router(router, prefix="/api/v1")

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
