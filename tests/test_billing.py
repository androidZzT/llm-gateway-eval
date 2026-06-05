from llm_gateway_eval.billing import analyze_usage_billing
from llm_gateway_eval.models import AssertionResult, EvalCase, EvalConfig, ProviderTarget, ReportOptions, RunOptions, RunResult, Usage


def test_analyze_usage_billing_flags_paired_input_discrepancy_and_total_issue() -> None:
    case = EvalCase(
        id="case-1",
        category="quality",
        messages=[{"role": "user", "content": "ping"}],
    )
    config = EvalConfig(
        run=RunOptions(),
        targets=[
            ProviderTarget(name="official", base_url="https://official.test/v1", api_key_env="OFFICIAL", model="m"),
            ProviderTarget(name="gateway", base_url="https://gateway.test/v1", api_key_env="GATEWAY", model="m"),
        ],
        report=ReportOptions(),
    )
    results = [
        _result("official", "case-1", Usage(input_tokens=100, output_tokens=20, total_tokens=120)),
        _result("gateway", "case-1", Usage(input_tokens=180, output_tokens=20, total_tokens=250)),
    ]

    analysis = analyze_usage_billing(config, [case], results)

    assert analysis["paired_comparison_count"] == 1
    assert analysis["paired_usage_discrepancy_count"] >= 1
    assert any(item["field"] == "input_tokens" for item in analysis["paired_usage_discrepancies"])
    assert analysis["total_consistency_issue_count"] == 1
    assert analysis["provider_usage"]["gateway"]["usage_complete_rate"] == 1.0


def _result(provider: str, case_id: str, usage: Usage) -> RunResult:
    return RunResult(
        case_id=case_id,
        category="quality",
        tags=[],
        provider=provider,
        model="m",
        output="pong",
        usage=usage,
        latency_seconds=0.1,
        ttft_seconds=None,
        error=None,
        attempts=1,
        assertion_results=[AssertionResult(type="contains", passed=True, message="ok")],
        cost=0.0,
        currency="USD",
        requested_model="m",
        repeat_index=1,
    )
