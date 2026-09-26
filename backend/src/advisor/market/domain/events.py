"""What the market tells the rest of the system, as domain facts.

How an event is delivered (the transactional outbox) is infrastructure;
``advisor.market.infra`` maps each of these to its outbox name and payload.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SubscriptionAdded:
    owner_id: uuid.UUID
    company_id: uuid.UUID
    company_name: str


@dataclass(frozen=True, slots=True)
class MarketSelected:
    owner_id: uuid.UUID
    market: str


@dataclass(frozen=True, slots=True)
class PostingsChanged:
    """About a company or a market, never a user: the crawler must not work
    out who is affected. The worker's dispatcher fans that out."""

    company_id: uuid.UUID | None
    market: str | None
    seen: int
    expired: int


MarketEvent = SubscriptionAdded | MarketSelected | PostingsChanged
