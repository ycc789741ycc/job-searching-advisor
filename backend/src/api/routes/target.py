"""Target HTTP surface: what a plan or a résumé can be aimed at."""

from __future__ import annotations

from fastapi import APIRouter

from api.dependencies import CurrentUser, Deps

router = APIRouter(tags=["target"])


@router.get("/targets")
async def list_targets(user: CurrentUser, deps: Deps) -> list[dict[str, object]]:
    """Matched openings, then watched roles, then pasted JDs. No AI runs."""
    return [
        {
            "kind": str(option.kind),
            "id": str(option.id),
            "title": option.title,
            "role_name": option.role_name,
            "role_id": str(option.role_id) if option.role_id else None,
            "company_name": option.company_name,
            "label": option.label,
            "fit": option.fit,
            "salary": (
                {
                    "min": option.salary.min_amount,
                    "max": option.salary.max_amount,
                    "currency": option.salary.currency,
                }
                if option.salary
                else None
            ),
            # atsBoard / jsonLd / publicApi for a crawled opening, "watchlist"
            # for a subscribed role, "pasted" for the user's own JD.
            "source_kind": option.source_kind,
            "url": option.url,
            "subscription_id": str(option.subscription_id) if option.subscription_id else None,
        }
        for option in await deps.target.options(user)
    ]
