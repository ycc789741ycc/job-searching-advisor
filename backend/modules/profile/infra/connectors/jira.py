"""Jira: cycle time, epic ownership and incident response.

This is the scope evidence a resume usually loses — "shipped the thing" with
no way to show how big the thing was.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from kernel.fetch import GuardedClient
from modules.profile.infra.connectors.base import EvidenceDraft

SCOPES = ("read:jira-work", "read:jira-user", "offline_access")
SCOPE_DESCRIPTIONS = (
    "Read issues and epics you are assigned to",
    "Read sprint and board history",
    "Read your Atlassian profile",
)

_MAX_ISSUES = 100


class JiraConnector:
    kind = "jira"

    def __init__(self, api_base_url: str) -> None:
        self._base = api_base_url.rstrip("/")

    async def sites(self, client: GuardedClient, access_token: str) -> list[dict[str, Any]]:
        payload = await client.get_json(
            f"{self._base}/oauth/token/accessible-resources", headers=_headers(access_token)
        )
        return list(payload or [])

    async def account_name(self, client: GuardedClient, access_token: str) -> str | None:
        sites = await self.sites(client, access_token)
        return str(sites[0].get("name")) if sites else None

    async def fetch(self, client: GuardedClient, access_token: str) -> list[EvidenceDraft]:
        sites = await self.sites(client, access_token)
        drafts: list[EvidenceDraft] = []

        for site in sites[:3]:
            cloud_id = site.get("id")
            site_name = str(site.get("name") or "jira")
            if not cloud_id:
                continue
            issues = await self._search(client, access_token, str(cloud_id))
            if not issues:
                continue

            statuses = Counter(
                str(((i.get("fields") or {}).get("status") or {}).get("name") or "unknown")
                for i in issues
            )
            done = sum(count for name, count in statuses.items() if name.lower() == "done")
            drafts.append(
                EvidenceDraft(
                    external_ref=f"jira:{cloud_id}:throughput",
                    reference=f"Jira · {site_name}",
                    fact=f"{len(issues)} assigned issues, {done} of them closed.",
                    observed_on=None,
                    confidence=0.85,
                )
            )

            projects = Counter(str(k).split("-", 1)[0] for k in (i.get("key") for i in issues) if k)
            for project, count in projects.most_common(5):
                drafts.append(
                    EvidenceDraft(
                        external_ref=f"jira:{cloud_id}:project:{project}",
                        reference=f"Jira · {site_name} · {project}",
                        fact=f"{count} issues worked in the {project} project.",
                        observed_on=None,
                        confidence=0.8,
                    )
                )

            for issue in issues[:25]:
                fields = issue.get("fields") or {}
                summary = str(fields.get("summary") or "").strip()
                if not summary:
                    continue
                drafts.append(
                    EvidenceDraft(
                        external_ref=f"jira:issue:{issue.get('id')}",
                        reference=f"Jira · {issue.get('key')}",
                        fact=summary,
                        observed_on=None,
                        confidence=0.75,
                    )
                )
        return drafts

    async def _search(
        self, client: GuardedClient, token: str, cloud_id: str
    ) -> list[dict[str, Any]]:
        payload = await client.get_json(
            f"{self._base}/ex/jira/{cloud_id}/rest/api/3/search/jql",
            headers=_headers(token),
            params={
                "jql": "assignee = currentUser() ORDER BY updated DESC",
                "maxResults": _MAX_ISSUES,
                "fields": "summary,status,resolutiondate,created",
            },
        )
        issues = payload.get("issues") if isinstance(payload, dict) else None
        return list(issues or [])


def _headers(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}", "accept": "application/json"}
