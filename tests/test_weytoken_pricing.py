from llm_gateway_eval.pricing import TokenPricing
from llm_gateway_eval.weytoken_pricing import (
    build_weytoken_price_rows,
    load_official_price_file,
    render_weytoken_pricing_html,
    render_weytoken_pricing_markdown,
)


def test_build_weytoken_price_rows_uses_frontend_formula() -> None:
    payload = {
        "success": True,
        "vendors": [{"id": 7, "name": "OpenAI"}],
        "group_ratio": {"codex专用分组": 2, "expensive": 5},
        "data": [
            {
                "model_name": "gpt-5.4-mini",
                "vendor_id": 7,
                "quota_type": 0,
                "model_ratio": 0.15,
                "completion_ratio": 8,
                "cache_ratio": 0.1,
                "enable_groups": ["codex专用分组", "expensive"],
                "supported_endpoint_types": ["openai"],
            }
        ],
    }

    rows = build_weytoken_price_rows(
        payload,
        group="best",
        official_prices={"gpt-5.4-mini": TokenPricing(0.75, 4.5, 0.075)},
        usd_cny_rate=6,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.input_per_million == 0.6
    assert row.cached_input_per_million == 0.06
    assert row.output_per_million == 4.8
    assert row.currency == "CNY"
    assert row.input_usd_per_million == 0.1
    assert row.output_usd_per_million == 0.8
    assert row.official_input_cny_per_million == 4.5
    assert row.official_output_cny_per_million == 27
    assert row.input_delta_percent == -86.67
    assert row.output_delta_percent == -82.22
    assert row.has_official_price


def test_render_weytoken_pricing_markdown() -> None:
    rows = build_weytoken_price_rows(
        {
            "success": True,
            "vendors": [{"id": 7, "name": "OpenAI"}],
            "group_ratio": {"codex专用分组": 2},
            "data": [
                {
                    "model_name": "gpt-5.4",
                    "vendor_id": 7,
                    "quota_type": 0,
                    "model_ratio": 0.5,
                    "completion_ratio": 8,
                    "cache_ratio": 0.1,
                    "enable_groups": ["codex专用分组"],
                    "supported_endpoint_types": ["openai"],
                }
            ],
        }
    )

    rendered = render_weytoken_pricing_markdown(rows)

    assert "WeyToken Pricing Comparison" in rendered
    assert "gpt-5.4" in rendered


def test_render_weytoken_pricing_html_labels_price_direction() -> None:
    rows = build_weytoken_price_rows(
        {
            "success": True,
            "vendors": [{"id": 7, "name": "OpenAI"}],
            "group_ratio": {"codex专用分组": 2},
            "data": [
                {
                    "model_name": "gpt-5.4-mini",
                    "vendor_id": 7,
                    "quota_type": 0,
                    "model_ratio": 0.15,
                    "completion_ratio": 8,
                    "cache_ratio": 0.1,
                    "enable_groups": ["codex专用分组"],
                    "supported_endpoint_types": ["openai"],
                }
            ],
        },
        official_prices={"gpt-5.4-mini": TokenPricing(0.075, 4.5, 0.0075)},
        usd_cny_rate=6,
    )

    rendered = render_weytoken_pricing_html(rows, generated_at="2026-06-02 18:00:00")

    assert "Input Delta" not in rendered
    assert "Output Delta" not in rendered
    assert "+6.67%" not in rendered
    assert "$" not in rendered
    assert "USD" not in rendered
    assert "¥0.6" in rendered
    assert "¥0.45" in rendered
    assert 'class="status expensive">贵 33.33%' in rendered
    assert 'class="status cheap">便宜 82.22%' in rendered


def test_cny_official_prices_are_compared_without_fx() -> None:
    rows = build_weytoken_price_rows(
        {
            "success": True,
            "vendors": [{"id": 8, "name": "Alibaba"}],
            "group_ratio": {"qwen分组": 1},
            "data": [
                {
                    "model_name": "qwen3.5-plus",
                    "vendor_id": 8,
                    "quota_type": 0,
                    "model_ratio": 0.2,
                    "completion_ratio": 6,
                    "enable_groups": ["qwen分组"],
                    "supported_endpoint_types": ["openai"],
                }
            ],
        },
        official_prices={"qwen3.5-plus": TokenPricing(0.8, 4.8, currency="CNY")},
        usd_cny_rate=6,
    )

    row = rows[0]

    assert row.input_per_million == 0.4
    assert row.output_per_million == 2.4
    assert row.official_currency == "CNY"
    assert row.official_input_cny_per_million == 0.8
    assert row.official_output_cny_per_million == 4.8
    assert row.input_delta_percent == -50
    assert row.output_delta_percent == -50


def test_load_official_price_file_skips_blank_template_rows(tmp_path) -> None:
    path = tmp_path / "official.csv"
    path.write_text(
        "model,vendor,input_per_million,cached_input_per_million,output_per_million,currency\n"
        "known,Vendor,1.0,0.1,2.0,USD\n"
        "missing,Vendor,,,,USD\n",
        encoding="utf-8",
    )

    prices = load_official_price_file(path)

    assert list(prices) == ["known"]
    assert prices["known"].input_per_million == 1.0
