"""GitHub: commits, reviews and the scope of what someone actually shipped.

Read-only scopes. Everything fetched is treated as untrusted text — repository
names and PR titles end up in prompts as data, never as instructions.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from kernel.errors import UpstreamFailedError
from kernel.parsing import parse_date
from kernel.fetch import GuardedClient
from modules.profile.infra.connectors.base import EvidenceDraft

SCOPES = ("read:user", "repo:status", "public_repo")
SCOPE_DESCRIPTIONS = (
    "Read repository metadata and commit history",
    "Read pull requests and review comments",
    "Read your public profile",
)

_MAX_ITEMS = 100


class GitHubConnector:
    kind = "github"

    def __init__(self, api_base_url: str) -> None:
        self._base = api_base_url.rstrip("/")

    async def account_name(self, client: GuardedClient, access_token: str) -> str | None:
        user = await self._get(client, access_token, "/user")
        return str(user.get("login")) if isinstance(user, dict) else None

    async def fetch(self, client: GuardedClient, access_token: str) -> list[EvidenceDraft]:
        login = await self.account_name(client, access_token)
        if not login:
            raise UpstreamFailedError("GitHub did not return an account")

        drafts: list[EvidenceDraft] = []
        merged = await self._search(
            client, access_token, f"is:pr author:{login} is:merged", _MAX_ITEMS
        )
        reviewed = await self._search(
            client, access_token, f"is:pr reviewed-by:{login}", _MAX_ITEMS
        )

        by_repo = Counter(_repo_of(item) for item in merged)
        for repo, count in by_repo.most_common(10):
            if not repo:
                continue
            drafts.append(
                EvidenceDraft(
                    external_ref=f"github:merged:{repo}",
                    reference=f"GitHub · {repo}",
                    fact=f"{count} merged pull requests authored in {repo}.",
                    observed_on=_latest_date(item for item in merged if _repo_of(item) == repo),
                    confidence=0.9,
                )
            )

        if reviewed:
            drafts.append(
                EvidenceDraft(
                    external_ref="github:reviews",
                    reference="GitHub reviews",
                    fact=(
                        f"{len(reviewed)} pull requests reviewed across "
                        f"{len({_repo_of(i) for i in reviewed})} repositories."
                    ),
                    observed_on=_latest_date(reviewed),
                    confidence=0.85,
                )
            )

        for item in merged[:25]:
            title = str(item.get("title") or "").strip()
            repo = _repo_of(item)
            if not title or not repo:
                continue
            drafts.append(
                EvidenceDraft(
                    external_ref=f"github:pr:{item.get('id')}",
                    reference=f"GitHub · {repo}#{item.get('number')}",
                    fact=title,
                    observed_on=_date_of(item),
                    confidence=0.8,
                )
            )
        return drafts

    async def _get(self, client: GuardedClient, token: str, path: str) -> Any:
        return await client.get_json(f"{self._base}{path}", headers=_headers(token))

    async def _search(
        self, client: GuardedClient, token: str, query: str, limit: int
    ) -> list[dict[str, Any]]:
        payload = await client.get_json(
            f"{self._base}/search/issues",
            headers=_headers(token),
            params={"q": query, "per_page": min(limit, 100), "sort": "updated"},
        )
        items = payload.get("items") if isinstance(payload, dict) else None
        return list(items or [])


def _headers(token: str) -> dict[str, str]:
    return {
        "authorization": f"Bearer {token}",
        "accept": "application/vnd.github+json",
        "x-github-api-version": "2022-11-28",
    }


def _repo_of(item: dict[str, Any]) -> str | None:
    url = str(item.get("repository_url") or "")
    return url.rsplit("/repos/", 1)[-1] if "/repos/" in url else None


def _date_of(item: dict[str, Any]) -> Any:
    return parse_date(item.get("closed_at") or item.get("updated_at"))


def _latest_date(items: Any) -> Any:
    dates = [d for d in (_date_of(i) for i in items) if d is not None]
    return max(dates) if dates else None
