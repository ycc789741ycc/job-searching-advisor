"""Provider adapters.

Every adapter speaks raw HTTP through ``kernel.fetch.GuardedClient`` rather
than a vendor SDK. That is deliberate: the user picks the provider *and* may
supply their own base URL, so every request has to pass the same SSRF guard and
be re-validated on each redirect. Routing one provider through its SDK and the
rest through HTTP would leave that guard with a hole in it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from kernel.fetch import GuardedClient


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    model: str


@dataclass(frozen=True, slots=True)
class Request:
    api_key: str
    model: str
    base_url: str
    system: str
    user: str
    max_output_tokens: int


class Provider(Protocol):
    name: str
    default_base_url: str

    async def complete(self, client: GuardedClient, request: Request) -> Completion: ...

    def stream(self, client: GuardedClient, request: Request) -> AsyncIterator[str]: ...
