"""Profile HTTP surface: connectors, resume upload and the evidence list.

Nothing here parses an uploaded file. The request handler stores the bytes and
queues a worker job; parsing hostile documents in the API process is exactly
what section 4 forbids.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel, Field

from app.dependencies import CurrentUser, Deps
from app.queue import enqueue
from kernel.config import Settings, must
from kernel.fetch import GuardedClient
from modules.profile.infra.connectors import github as github_connector
from modules.profile.infra.connectors import jira as jira_connector
from modules.profile.infra.oauth import authorize_url, exchange_code, sign_state, verify_state

router = APIRouter(tags=["profile"])


def _redirect_uri(settings: Settings, kind: str) -> str:
    """Where the provider sends the browser back to: a page in the SPA.

    It has to be the SPA, not this API. The provider redirects with a GET
    carrying `code` and `state`, but exchanging them needs the user's access
    token, which lives only in the SPA's memory. So the SPA receives the
    redirect and POSTs both to `/connections/{kind}/callback` here.

    Built explicitly, because an f-string over an unset value would quietly
    produce "None/connections/..." and fail at the provider instead of here.
    """
    base = must(settings.oauth_redirect_base_url, "OAUTH_REDIRECT_BASE_URL")
    return f"{base}/connections/{kind}/callback"


SCOPE_COPY = {
    "github": github_connector.SCOPE_DESCRIPTIONS,
    "jira": jira_connector.SCOPE_DESCRIPTIONS,
}


class CallbackRequest(BaseModel):
    code: str = Field(min_length=1)
    state: str = Field(min_length=1)


class AnswerRequest(BaseModel):
    answer: str = Field(min_length=1)


@router.get("/connections")
async def list_connections(user: CurrentUser, deps: Deps) -> list[dict[str, object]]:
    connected = {c.kind: c for c in await deps.profile.connections(user)}
    rows: list[dict[str, object]] = []
    for kind, scopes in SCOPE_COPY.items():
        connection = connected.get(kind)
        synced = connection.last_synced_at if connection is not None else None
        rows.append(
            {
                "kind": kind,
                "connected": connection is not None,
                "account": connection.account if connection is not None else None,
                "status": connection.status if connection is not None else "disconnected",
                "last_synced_at": synced.isoformat() if synced is not None else None,
                "last_error": connection.last_error if connection is not None else None,
                "scopes": list(scopes),
            }
        )
    return rows


@router.get("/connections/{kind}/authorize-url")
async def start_authorization(kind: str, user: CurrentUser, deps: Deps) -> dict[str, str]:
    settings = deps.settings
    secret = settings.require_master_key().get_secret_value()
    client_id = (
        must(settings.github_oauth_client_id, "GITHUB_OAUTH_CLIENT_ID")
        if kind == "github"
        else must(settings.jira_oauth_client_id, "JIRA_OAUTH_CLIENT_ID")
    )
    return {
        "url": authorize_url(
            kind,
            jira_oauth_base=must(settings.jira_oauth_base_url, "JIRA_OAUTH_BASE_URL"),
            client_id=client_id,
            redirect_uri=_redirect_uri(settings, kind),
            state=sign_state(user, kind, secret=secret),
        )
    }


@router.post("/connections/{kind}/callback", status_code=201)
async def complete_authorization(
    kind: str, body: CallbackRequest, user: CurrentUser, deps: Deps
) -> dict[str, object]:
    settings = deps.settings
    secret = settings.require_master_key().get_secret_value()
    owner_id, state_kind = verify_state(body.state, secret=secret)
    if owner_id != user or state_kind != kind:
        from kernel.errors import ForbiddenError

        raise ForbiddenError("this authorization was started by someone else")

    client_id, client_secret = (
        (
            must(settings.github_oauth_client_id, "GITHUB_OAUTH_CLIENT_ID"),
            must(settings.github_oauth_client_secret, "GITHUB_OAUTH_CLIENT_SECRET"),
        )
        if kind == "github"
        else (
            must(settings.jira_oauth_client_id, "JIRA_OAUTH_CLIENT_ID"),
            must(settings.jira_oauth_client_secret, "JIRA_OAUTH_CLIENT_SECRET"),
        )
    )

    async with GuardedClient(
        timeout_seconds=settings.crawl_http_timeout_seconds, user_agent=settings.service_name
    ) as client:
        token = await exchange_code(
            client,
            kind,
            jira_oauth_base=must(settings.jira_oauth_base_url, "JIRA_OAUTH_BASE_URL"),
            code=body.code,
            client_id=client_id,
            client_secret=client_secret.get_secret_value(),
            redirect_uri=_redirect_uri(settings, kind),
        )

    connection = await deps.profile.store_connection(
        user,
        kind=kind,
        access_token=str(token["access_token"]),
        refresh_token=token.get("refresh_token"),
        scopes=tuple(str(token.get("scope", "")).split()),
        expires_at=None,
    )
    await enqueue("profile.sync_connection", owner_id=str(user), kind=kind)
    return {"kind": connection.kind, "status": connection.status}


@router.post("/connections/{kind}/sync", status_code=202)
async def sync_now(kind: str, user: CurrentUser, deps: Deps) -> dict[str, str]:
    await enqueue("profile.sync_connection", owner_id=str(user), kind=kind)
    return {"status": "queued"}


@router.delete("/connections/{kind}", status_code=204)
async def disconnect(kind: str, user: CurrentUser, deps: Deps) -> None:
    await deps.profile.disconnect(user, kind)


@router.post("/resumes", status_code=202)
async def upload_resume(
    user: CurrentUser, deps: Deps, file: UploadFile = File(...)
) -> dict[str, object]:
    content = await file.read()
    resume = await deps.profile.upload_resume(
        user,
        filename=file.filename or "resume",
        content_type=file.content_type or "application/octet-stream",
        content=content,
    )
    await enqueue("profile.parse_resume", owner_id=str(user), resume_id=str(resume.id))
    return {"id": str(resume.id), "filename": resume.filename, "status": "parsing"}


@router.get("/resumes")
async def list_resumes(user: CurrentUser, deps: Deps) -> list[dict[str, object]]:
    return [
        {
            "id": str(r.id),
            "filename": r.filename,
            "status": r.status,
            "parse_error": r.parse_error,
            "uploaded_at": r.uploaded_at.isoformat(),
        }
        for r in await deps.profile.resumes(user)
    ]


@router.get("/resumes/{resume_id}/download-url")
async def resume_url(resume_id: uuid.UUID, user: CurrentUser, deps: Deps) -> dict[str, str]:
    """Uploads are never publicly addressable; this is short-lived."""
    return {"url": await deps.profile.resume_download_url(user, resume_id)}


@router.get("/evidence")
async def list_evidence(user: CurrentUser, deps: Deps) -> list[dict[str, object]]:
    snapshot = await deps.profile.snapshot(user)
    return [
        {
            "id": str(e.id),
            "source": str(e.source),
            "reference": e.reference,
            "fact": e.fact,
            "observed_on": e.observed_on.isoformat() if e.observed_on else None,
            "confidence": e.confidence,
        }
        for e in snapshot.evidence
    ]


@router.get("/profile")
async def read_profile(user: CurrentUser, deps: Deps) -> dict[str, object]:
    snapshot = await deps.profile.snapshot(user)
    return {
        "version": snapshot.version,
        "evidence_count": len(snapshot.evidence),
        "total_experience_months": snapshot.total_experience_months,
        "positions": [
            {
                "title": p.title,
                "company": p.company,
                "started_on": p.started_on.isoformat(),
                "ended_on": p.ended_on.isoformat() if p.ended_on else None,
            }
            for p in snapshot.positions
        ],
    }


__all__ = ["AnswerRequest", "router"]
