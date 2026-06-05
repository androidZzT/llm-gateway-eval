from llm_gateway_eval.models import AssertionResult, RunResult, Usage
from llm_gateway_eval.routing import analyze_routing_degradation


def test_analyze_routing_degradation_flags_quality_gap_and_variation() -> None:
    results = [
        _result("official", "case-1", passed=True, repeat=1, input_tokens=100),
        _result("official", "case-1", passed=True, repeat=2, input_tokens=100),
        _result("gateway", "case-1", passed=False, repeat=1, input_tokens=100, model="cheap-model"),
        _result("gateway", "case-1", passed=True, repeat=2, input_tokens=180, model="m"),
    ]

    analysis = analyze_routing_degradation(results)

    assert analysis["risk_level"] in {"MEDIUM", "HIGH"}
    assert analysis["quality_gap_event_count"] == 1
    assert analysis["input_usage_variation_event_count"] == 1
    assert analysis["pass_flap_event_count"] == 1
    assert analysis["model_variant_event_count"] == 1


def _result(
    provider: str,
    case_id: str,
    passed: bool,
    repeat: int,
    input_tokens: int,
    model: str = "m",
) -> RunResult:
    return RunResult(
        case_id=case_id,
        category="model_authenticity",
        tags=["authenticity"],
        provider=provider,
        model=model,
        output="ok" if passed else "bad",
        usage=Usage(input_tokens=input_tokens, output_tokens=5, total_tokens=input_tokens + 5),
        latency_seconds=0.1,
        ttft_seconds=None,
        error=None,
        attempts=1,
        assertion_results=[AssertionResult(type="equals", passed=passed, message="ok")],
        cost=0.0,
        currency="USD",
        requested_model="m",
        repeat_index=repeat,
    )
