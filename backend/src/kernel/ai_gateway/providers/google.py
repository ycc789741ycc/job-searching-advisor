"""Google Generative Language API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from kernel.ai_gateway.providers.anthropic import _raise_for_status
from kernel.ai_gateway.providers.base import Completion, Request
from kernel.fetch import GuardedClient


class GoogleProvider:
    name = "google"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta"

    async def complete(self, client: GuardedClient, request: Request) -> Completion:
        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": request.system}]},
            "contents": [{"role": "user", "parts": [{"text": request.user}]}],
            "generationConfig": {"maxOutputTokens": request.max_output_tokens},
        }
        response = await client.request(
            "POST",
            f"{request.base_url.rstrip('/')}/models/{request.model}:generateContent",
            headers={
                "content-type": "application/json",
                "x-goog-api-key": request.api_key,
            },
            json=body,
        )
        _raise_for_status(response.status_code, response.text)
        payload = response.json()

        candidates = payload.get("candidates") or [{}]
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(str(part.get("text", "")) for part in parts)
        usage = payload.get("usageMetadata", {})
        return Completion(
            text=text,
            input_tokens=int(usage.get("promptTokenCount", 0)),
            output_tokens=int(usage.get("candidatesTokenCount", 0)),
            model=request.model,
        )

    async def stream(self, client: GuardedClient, request: Request) -> AsyncIterator[str]:
        """Google's streaming wire format differs enough to be its own job.

        Phase 1 has no streaming feature on this provider (resume chat is Phase
        3), so the whole response is yielded as one chunk rather than leaving a
        half-built SSE parser in the tree.
        """
        completion = await self.complete(client, request)
        yield completion.text
