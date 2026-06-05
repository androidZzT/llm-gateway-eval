from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class TokenPricing:
    input_per_million: float
    output_per_million: float
    cached_input_per_million: float | None = None
    currency: str = "USD"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Snapshot from OpenAI public API pricing checked on 2026-06-02.
# Override from CLI when prices change or when using Batch, Flex, Priority, or regional pricing.
OPENAI_STANDARD_PRICING: dict[str, TokenPricing] = {
    "gpt-5.5": TokenPricing(input_per_million=5.00, cached_input_per_million=0.50, output_per_million=30.00),
    "gpt-5.4": TokenPricing(input_per_million=2.50, cached_input_per_million=0.25, output_per_million=15.00),
    "gpt-5.4-low": TokenPricing(input_per_million=2.50, cached_input_per_million=0.25, output_per_million=15.00),
    "gpt-5.4-mini": TokenPricing(input_per_million=0.75, cached_input_per_million=0.075, output_per_million=4.50),
}


def official_pricing_for_model(model: str | None) -> TokenPricing | None:
    if not model:
        return None
    return OPENAI_STANDARD_PRICING.get(model)


def scaled_pricing(pricing: TokenPricing, multiplier: float) -> TokenPricing:
    return TokenPricing(
        input_per_million=pricing.input_per_million * multiplier,
        cached_input_per_million=(
            None if pricing.cached_input_per_million is None else pricing.cached_input_per_million * multiplier
        ),
        output_per_million=pricing.output_per_million * multiplier,
        currency=pricing.currency,
    )


def calculate_token_cost(usage: dict[str, int], pricing: TokenPricing | None) -> float | None:
    if pricing is None or not usage:
        return None
    input_tokens = usage.get("input_tokens", 0)
    cached_input_tokens = usage.get("cached_input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    uncached_input_tokens = max(input_tokens - cached_input_tokens, 0)
    cached_rate = (
        pricing.cached_input_per_million
        if pricing.cached_input_per_million is not None
        else pricing.input_per_million
    )
    cost = (
        uncached_input_tokens * pricing.input_per_million / 1_000_000
        + cached_input_tokens * cached_rate / 1_000_000
        + output_tokens * pricing.output_per_million / 1_000_000
    )
    return round(cost, 8)
