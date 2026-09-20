"""Cost estimation.

Two places need this: the budget check before every call, and the
"show cost before spending" confirmation on a user's first analysis and first
role map (domain decision in section 2.8).

The estimate is an estimate. Token counts here come from a character
heuristic, and the rate for a model we have no published price for is
deliberately pessimistic, so the user is never surprised by a larger bill than
the number they approved.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

_PRICING_FILE = Path(__file__).parent / "pricing.json"

# Rough across-the-board ratio for English prose and JSON. Good enough for a
# budget guard; the ledger records the provider's own reported counts.
_CHARS_PER_TOKEN = 4


@dataclass(frozen=True, slots=True)
class Rate:
    input_per_mtok: Decimal
    output_per_mtok: Decimal
    is_published: bool


@dataclass(frozen=True, slots=True)
class CostEstimate:
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    # False when we had no published rate and used the conservative fallback.
    rate_is_published: bool


@lru_cache(maxsize=1)
def _table() -> dict[str, object]:
    return dict(json.loads(_PRICING_FILE.read_text(encoding="utf-8")))


def rate_for(model: str) -> Rate:
    models: dict[str, dict[str, float]] = _table()["models"]  # type: ignore[assignment]
    entry = models.get(model)
    if entry is not None:
        return Rate(
            input_per_mtok=Decimal(str(entry["input_per_mtok"])),
            output_per_mtok=Decimal(str(entry["output_per_mtok"])),
            is_published=True,
        )
    fallback: dict[str, float] = _table()["unknown_model_rate"]  # type: ignore[assignment]
    return Rate(
        input_per_mtok=Decimal(str(fallback["input_per_mtok"])),
        output_per_mtok=Decimal(str(fallback["output_per_mtok"])),
        is_published=False,
    )


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN)


def cost_of(model: str, *, input_tokens: int, output_tokens: int) -> Decimal:
    rate = rate_for(model)
    million = Decimal(1_000_000)
    return (
        Decimal(input_tokens) * rate.input_per_mtok / million
        + Decimal(output_tokens) * rate.output_per_mtok / million
    )


def estimate(model: str, *, prompt: str, expected_output_tokens: int) -> CostEstimate:
    input_tokens = estimate_tokens(prompt)
    rate = rate_for(model)
    return CostEstimate(
        input_tokens=input_tokens,
        output_tokens=expected_output_tokens,
        cost_usd=cost_of(model, input_tokens=input_tokens, output_tokens=expected_output_tokens),
        rate_is_published=rate.is_published,
    )
