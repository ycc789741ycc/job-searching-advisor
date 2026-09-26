"""Anthropic Messages API."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from kernel.ai_gateway.providers.base import Completion, Request
from kernel.errors import CredentialFailedError, ProviderUnavailableError
from kernel.fetch import GuardedClient

API_VERSION = "2023-06-01"


class AnthropicProvider:
    name = "anthropic"
    default_base_url = "https://api.anthropic.com"

    def _headers(self, request: Request) -> dict[str, str]:
        return {
            "x-api-key": request.api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }

    def _body(self, request: Request, *, stream: bool) -> dict[str, Any]:
        return {
            "model": request.model,
            "max_tokens": request.max_output_tokens,
            "system": request.system,
            "messages": [{"role": "user", "content": request.user}],
            "stream": stream,
        }

    async def complete(self, client: GuardedClient, request: Request) -> Completion:
        response = await client.request(
            "POST",
            f"{request.base_url.rstrip('/')}/v1/messages",
            headers=self._headers(request),
            json=self._body(request, stream=False),
        )
        _raise_for_status(response.status_code, response.text)
        payload = response.json()

        text = "".join(
            block.get("text", "")
            for block in payload.get("content", [])
            if block.get("type") == "text"
        )
        usage = payload.get("usage", {})
        return Completion(
            text=text,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            model=str(payload.get("model", request.model)),
        )

    async def stream(self, client: GuardedClient, request: Request) -> AsyncIterator[str]:
        response = await client.request(
            "POST",
            f"{request.base_url.rstrip('/')}/v1/messages",
            headers=self._headers(request),
            json=self._body(request, stream=True),
        )
        _raise_for_status(response.status_code, response.text)
        for line in response.text.splitlines():
            if not line.startswith("data: "):
                continue
            try:
                event = json.loads(line.removeprefix("data: "))
            except ValueError:
                continue
            if event.get("type") == "content_block_delta":
                piece = event.get("delta", {}).get("text")
                if piece:
                    yield str(piece)


def _raise_for_status(status: int, body: str) -> None:
    if status in (401, 403):
        raise CredentialFailedError("the provider rejected this API key", status=status)
    if status == 429:
        raise CredentialFailedError("the provider rate-limited this key", status=status)
    if status >= 400:
        # The body may echo user content, so it is not passed to the client.
        raise ProviderUnavailableError(f"provider returned {status}", status=status)
