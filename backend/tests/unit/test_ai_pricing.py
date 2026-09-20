"""Cost estimation, including the case where we have no published rate."""

from __future__ import annotations

from decimal import Decimal

from kernel.ai_gateway import pricing


def test_a_published_model_uses_its_real_rate() -> None:
    rate = pricing.rate_for("claude-opus-5")
    assert rate.is_published
    assert rate.input_per_mtok == Decimal("5.0")
    assert rate.output_per_mtok == Decimal("25.0")


def test_an_unknown_model_falls_back_conservatively() -> None:
    """A user must never be surprised by a bill larger than what they approved."""
    unknown = pricing.rate_for("some-model-we-have-no-price-for")
    opus = pricing.rate_for("claude-opus-5")
    assert not unknown.is_published
    assert unknown.input_per_mtok > opus.input_per_mtok
    assert unknown.output_per_mtok > opus.output_per_mtok


def test_cost_scales_with_both_directions_of_tokens() -> None:
    cheap = pricing.cost_of("claude-opus-5", input_tokens=1_000, output_tokens=100)
    dear = pricing.cost_of("claude-opus-5", input_tokens=1_000, output_tokens=10_000)
    assert dear > cheap


def test_one_million_input_tokens_costs_the_published_input_rate() -> None:
    assert pricing.cost_of(
        "claude-sonnet-5", input_tokens=1_000_000, output_tokens=0
    ) == Decimal("2.0")


def test_estimate_reports_whether_the_rate_was_published() -> None:
    known = pricing.estimate("claude-haiku-4-5", prompt="x" * 400, expected_output_tokens=500)
    assert known.rate_is_published
    assert known.input_tokens == 100

    guessed = pricing.estimate("mystery-model", prompt="x" * 400, expected_output_tokens=500)
    assert not guessed.rate_is_published
    assert guessed.cost_usd > known.cost_usd
