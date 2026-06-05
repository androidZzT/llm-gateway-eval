import json

from llm_gateway_eval.metrics import aggregate_results
from llm_gateway_eval.models import (
    AssertionResult,
    EvalConfig,
    ProviderTarget,
    ReportOptions,
    RunOptions,
    RunResult,
    Usage,
)
from llm_gateway_eval.report import render_report


def test_render_report(tmp_path) -> None:
    config = EvalConfig(
        run=RunOptions(),
        targets=[
            ProviderTarget(
                name="mock",
                base_url="http://example.test/v1",
                api_key_env="KEY",
                model="mock",
            )
        ],
        report=ReportOptions(),
    )
    result = RunResult(
        case_id="case-1",
        category="quality",
        tags=[],
        provider="mock",
        model="mock",
        output="pong",
        usage=Usage(input_tokens=1, output_tokens=1, total_tokens=2),
        latency_seconds=0.1,
        ttft_seconds=None,
        error=None,
        attempts=1,
        assertion_results=[AssertionResult(type="equals", passed=True, message="ok")],
        cost=0.0,
        currency="USD",
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "summary.json").write_text(
        json.dumps(aggregate_results(config, [result]), ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / "results.jsonl").write_text(json.dumps(result.to_dict(), ensure_ascii=False) + "\n", encoding="utf-8")

    report_path = render_report(run_dir, tmp_path / "report.md")

    rendered = report_path.read_text(encoding="utf-8")
    assert "Provider Scores" in rendered
    assert "mock" in rendered

