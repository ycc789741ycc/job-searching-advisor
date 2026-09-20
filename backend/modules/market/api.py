"""Market HTTP surface: watched companies, chosen markets and pasted JDs."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.dependencies import CurrentUser, Deps
from app.queue import enqueue
from modules.market.public import Coverage

router = APIRouter(tags=["market"])


class SubscriptionRequest(BaseModel):
    company_name: str = Field(min_length=1, max_length=255)


class MarketRequest(BaseModel):
    market: str = Field(min_length=1, max_length=128)


class JobDescriptionRequest(BaseModel):
    company_name: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=512)
    location: str | None = None
    description: str = Field(min_length=1)
    url: str | None = None


@router.get("/company-subscriptions")
async def list_subscriptions(user: CurrentUser, deps: Deps) -> list[dict[str, object]]:
    return [
        {
            "company_id": str(s.company_id),
            "company_name": s.company_name,
            # `manual` means there is no supported job board, so the user sees
            # plainly that nothing updates automatically.
            "coverage": str(s.coverage),
            "last_refreshed_at": s.last_refreshed_at.isoformat() if s.last_refreshed_at else None,
        }
        for s in await deps.market.subscriptions(user)
    ]


@router.post("/company-subscriptions", status_code=201)
async def subscribe(body: SubscriptionRequest, user: CurrentUser, deps: Deps) -> dict[str, object]:
    subscription = await deps.market.subscribe(user, company_name=body.company_name)
    await enqueue(
        "market.discover_board",
        owner_id=str(user),
        company_id=str(subscription.company_id),
        company_name=subscription.company_name,
    )
    return {
        "company_id": str(subscription.company_id),
        "company_name": subscription.company_name,
        "coverage": str(subscription.coverage),
    }


@router.delete("/company-subscriptions/{company_id}", status_code=204)
async def unsubscribe(company_id: uuid.UUID, user: CurrentUser, deps: Deps) -> None:
    await deps.market.unsubscribe(user, company_id)


@router.post("/company-subscriptions/{company_id}/refresh", status_code=202)
async def refresh(company_id: uuid.UUID, user: CurrentUser, deps: Deps) -> dict[str, str]:
    """Re-crawl one watched company now. Rate limited; weekly stays the norm."""
    await deps.market.request_manual_refresh(user, company_id)
    await enqueue("market.refresh_company", owner_id=str(user), company_id=str(company_id))
    return {"status": "queued"}


@router.get("/market-preferences")
async def list_markets(user: CurrentUser, deps: Deps) -> list[str]:
    return await deps.market.markets(user)


@router.post("/market-preferences", status_code=201)
async def add_market(body: MarketRequest, user: CurrentUser, deps: Deps) -> list[str]:
    return await deps.market.add_market(user, body.market)


@router.delete("/market-preferences/{market}")
async def remove_market(market: str, user: CurrentUser, deps: Deps) -> list[str]:
    return await deps.market.remove_market(user, market)


@router.get("/job-descriptions")
async def list_pasted(user: CurrentUser, deps: Deps) -> list[dict[str, object]]:
    return [
        {
            "id": str(p.id),
            "company_name": p.company_name,
            "title": p.title,
            "location": p.location,
            "visibility": str(p.visibility),
        }
        for p in await deps.market.private_postings(user)
    ]


@router.post("/job-descriptions", status_code=201)
async def paste(body: JobDescriptionRequest, user: CurrentUser, deps: Deps) -> dict[str, object]:
    """A pasted JD is private to its owner and never enters shared data."""
    posting = await deps.market.paste_job_description(
        user,
        company_name=body.company_name,
        title=body.title,
        location=body.location,
        description=body.description,
        url=body.url,
    )
    return {
        "id": str(posting.id),
        "company_name": posting.company_name,
        "title": posting.title,
        "visibility": str(posting.visibility),
    }


__all__ = ["Coverage", "router"]
