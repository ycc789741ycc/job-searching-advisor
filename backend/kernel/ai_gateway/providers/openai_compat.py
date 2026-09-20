"""OpenAI and any OpenAI-compatible endpoint.

This adapter also covers the "Local" provider in the UI: a model the user runs
themselves, reachable at a public URL they control. The SSRF guard still
applies, so it cannot point at our own network.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from kernel.ai_gateway.providers.anthropic import _raise_for_status
from kernel.ai_gateway.providers.base import Completion, Request
from kernel.fetch import GuardedClient


class OpenAICompatibleProvider:
    name = "openai"
    default_base_url = "https://api.openai.com/v1"

    def _headers(self, request: Request) -> dict[str, str]:
        return {
            "authorization": f"Bearer {request.api_key}",
            "content-type": "application/json",
        }

    def _body(self, request: Request, *, stream: bool) -> dict[str, Any]:
        return {
            "model": request.model,
            "max_completion_tokens": request.max_output_tokens,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "stream": stream,
        }

    async def complete(self, client: GuardedClient, request: Request) -> Completion:
        response = await client.request(
            "POST",
            f"{request.base_url.rstrip('/')}/chat/completions",
            headers=self._headers(request),
            json=self._body(request, stream=False),
        )
        _raise_for_status(response.status_code, response.text)
        payload = response.json()

        choices = payload.get("choices") or [{}]
        text = (choices[0].get("message") or {}).get("content") or ""
        usage = payload.get("usage", {})
        return Completion(
            text=str(text),
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            model=str(payload.get("model", request.model)),
        )

    async def stream(self, client: GuardedClient, request: Request) -> AsyncIterator[str]:
        response = await client.request(
            "POST",
            f"{request.base_url.rstrip('/')}/chat/completions",
            headers=self._headers(request),
            json=self._body(request, stream=True),
        )
        _raise_for_status(response.status_code, response.text)
        for line in response.text.splitlines():
            if not line.startswith("data: "):
                continue
            chunk = line.removeprefix("data: ").strip()
            if chunk == "[DONE]":
                break
            try:
                event = json.loads(chunk)
            except ValueError:
                continue
            for choice in event.get("choices", []):
                piece = (choice.get("delta") or {}).get("content")
                if piece:
                    yield str(piece)


class LocalProvider(OpenAICompatibleProvider):
    """Same wire format; the user always supplies the base URL."""

    name = "local"
    default_base_url = ""
