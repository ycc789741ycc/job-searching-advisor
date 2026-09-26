"""Mapping typed domain errors onto HTTP.

Stable codes go out; internal detail and stack traces never do.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from kernel.errors import HTTP_STATUS_BY_CODE, DomainError, ErrorCode
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

    @app.exception_handler(RequestValidationError)
    async def _invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        """Map request-shape failures onto the same envelope as everything else.

        FastAPI's default body is a list of Pydantic error objects, which a
        client would have to know how to read. A sign-up form should be able to
        show "That does not look like an email address" without parsing that.
        """
        log.info("request.invalid", path=request.url.path)
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": str(ErrorCode.VALIDATION_FAILED),
                    "message": _readable(exc),
                }
            },
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


def _readable(exc: RequestValidationError) -> str:
    """One sentence a person can act on, from Pydantic's first complaint."""
    errors = exc.errors()
    if not errors:
        return "That request could not be read."

    first = errors[0]
    # ("body", "email") -> "email"
    location = [str(part) for part in first.get("loc", ()) if part != "body"]
    field = location[-1] if location else None
    detail = str(first.get("msg", "is not valid")).removeprefix("Value error, ")

    if field:
        return f"{field}: {detail}"
    return detail


def error_response(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}
