"""Mapping typed domain errors onto HTTP.

Stable codes go out; internal detail and stack traces never do.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from kernel.errors import HTTP_STATUS_BY_CODE, DomainError
from kernel.logging import get_logger

log = get_logger(__name__)


def install(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain_error(request: Request, exc: DomainError) -> JSONResponse:
        status = HTTP_STATUS_BY_CODE.get(exc.code, 400)
        if status >= 500:
            log.error("request.failed", code=str(exc.code), path=request.url.path)
        else:
            log.info("request.rejected", code=str(exc.code), path=request.url.path)
        return JSONResponse(
            status_code=status,
            content={"error": {"code": str(exc.code), "message": exc.message}},
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        # The detail is logged, never returned.
        log.error(
            "request.unhandled",
            path=request.url.path,
            error_type=exc.__class__.__name__,
        )
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "something went wrong"}},
        )


def error_response(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}
