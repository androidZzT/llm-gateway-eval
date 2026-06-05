from llm_gateway_eval.pricing import TokenPricing, calculate_token_cost, official_pricing_for_model, scaled_pricing


def test_calculate_token_cost_accounts_for_cached_input() -> None:
    pricing = TokenPricing(input_per_million=10, cached_input_per_million=1, output_per_million=20)
    usage = {"input_tokens": 1000, "cached_input_tokens": 200, "output_tokens": 100}

    assert calculate_token_cost(usage, pricing) == 0.0102


def test_official_pricing_catalog_and_multiplier() -> None:
    official = official_pricing_for_model("gpt-5.4-mini")
    assert official is not None
    gateway = scaled_pricing(official, 2)

    assert gateway.input_per_million == official.input_per_million * 2
    assert gateway.output_per_million == official.output_per_million * 2

