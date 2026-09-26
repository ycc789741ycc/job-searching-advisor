"""Connector contract.

A connector turns one authorised source into ``EvidenceDraft`` rows. It runs
only in the worker's ``sync`` queue, because that is the only place the
connector OAuth tokens can be decrypted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from kernel.fetch import GuardedClient


@dataclass(frozen=True, slots=True)
class EvidenceDraft:
    """``external_ref`` makes a re-sync update a fact rather than duplicate it."""

    external_ref: str
    reference: str
    fact: str
    observed_on: date | None
    confidence: float


class Connector(Protocol):
    kind: str

    async def fetch(self, client: GuardedClient, access_token: str) -> list[EvidenceDraft]: ...
