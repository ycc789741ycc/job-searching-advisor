"""The ``api`` deployable: HTTP, SSE and nothing else.

No business rules live here — routers map HTTP onto module services. Uploaded
documents are stored and queued, never parsed in a request handler.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import errors
from kernel.config import Unit, get_settings
from kernel.logging import configure_logging, get_logger
from wiring.container import container
from wiring.queue import queue

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

    from api.routes.assessment import router as assessment_router
    from api.routes.gapplan import router as gapplan_router
    from api.routes.identity import router as identity_router
    from api.routes.market import router as market_router
    from api.routes.profile import router as profile_router
    from api.routes.resume import router as resume_router
    from api.routes.rolemap import router as rolemap_router
    from api.routes.target import router as target_router

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
