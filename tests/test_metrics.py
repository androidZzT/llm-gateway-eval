from llm_gateway_eval.metrics import aggregate_results, calculate_cost
from llm_gateway_eval.models import (
    AssertionResult,
    EvalConfig,
    Pricing,
    ProviderTarget,
    ReportOptions,
    RunOptions,
    RunResult,
    Usage,
)


def test_calculate_cost() -> None:
    usage = Usage(input_tokens=1000, output_tokens=500)
    pricing = Pricing(input_per_million=2.0, output_per_million=4.0)

    assert calculate_cost(usage, pricing) == 0.004


def test_aggregate_results_scores_provider() -> None:
    config = EvalConfig(
        run=RunOptions(performance_targets={"p95_latency_seconds": 2}),
        targets=[
            ProviderTarget(
                name="mock",
                base_url="http://example.test/v1",
                api_key_env="KEY",
                model="mock",
                pricing=Pricing(input_per_million=1, output_per_million=1),
            )
        ],
        report=ReportOptions(),
    )
    result = RunResult(
        case_id="case-1",
        category="safety",
        tags=["safety"],
        provider="mock",
        model="mock",
        output="cannot comply",
        usage=Usage(input_tokens=10, output_tokens=5, total_tokens=15),
        latency_seconds=1.0,
        ttft_seconds=None,
        error=None,
        attempts=1,
        assertion_results=[AssertionResult(type="refusal_expected", passed=True, message="ok")],
        cost=calculate_cost(Usage(input_tokens=10, output_tokens=5), Pricing(1, 1)),
        currency="USD",
    )

    summary = aggregate_results(config, [result])

    provider = summary["providers"]["mock"]
    assert provider["case_pass_rate"] == 1.0
    assert provider["latency"]["p95"] == 1.0
    assert provider["scores"]["quality"] == 100
    assert provider["scores"]["security_compliance"] == 100
    assert provider["overall_score"] > 0

