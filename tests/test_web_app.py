import json

from typer.testing import CliRunner

from llm_gateway_eval.cli import app
from llm_gateway_eval.web_app import render_eval_web_app


def _write_json(path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_jsonl(path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _make_artifacts(tmp_path):
    coding = tmp_path / "coding"
    security = tmp_path / "security"
    benchmark = tmp_path / "benchmark-plan.json"
    _write_json(
        coding / "summary.json",
        {
            "total_runs": 2,
            "task_count": 1,
            "model_override": "gpt-test",
            "targets_summary": {
                "official": {
                    "runs": 1,
                    "passed": 1,
                    "pass_rate": 1,
                    "avg_codex_duration_seconds": 10,
                    "usage": {"input_tokens": 100, "cached_input_tokens": 10, "output_tokens": 20, "reasoning_output_tokens": 5, "total_tokens": 120},
                },
                "gateway": {
                    "runs": 1,
                    "passed": 1,
                    "pass_rate": 1,
                    "avg_codex_duration_seconds": 11,
                    "usage": {"input_tokens": 90, "cached_input_tokens": 8, "output_tokens": 18, "reasoning_output_tokens": 6, "total_tokens": 108},
                },
            },
            "paired_task_deltas": [
                {"task_id": "task_one", "target_pass_rates": {"official": 1, "gateway": 1}, "max_delta": 0}
            ],
        },
    )
    _write_jsonl(
        coding / "results.jsonl",
        [
            {
                "task_id": "task_one",
                "target": "official",
                "repeat_index": 1,
                "passed": True,
                "codex_duration_seconds": 10,
                "verify_duration_seconds": 0.1,
                "usage": {"total_tokens": 120, "reasoning_output_tokens": 5},
                "changed_files": ["main.py"],
                "error": None,
            },
            {
                "task_id": "task_one",
                "target": "gateway",
                "repeat_index": 1,
                "passed": True,
                "codex_duration_seconds": 11,
                "verify_duration_seconds": 0.1,
                "usage": {"total_tokens": 108, "reasoning_output_tokens": 6},
                "changed_files": ["main.py"],
                "error": None,
            },
        ],
    )
    _write_json(
        security / "summary.json",
        {
            "quick_eval": {"gateway_url": "https://gateway.example/v1", "model": "gpt-test"},
            "providers": {
                "gateway": {
                    "total": 2,
                    "request_success_count": 1,
                    "request_success_rate": 0.5,
                    "error_count": 1,
                    "error_types": {"http_429": 1},
                }
            },
            "security_analysis": {"canary_leakage_event_count": 0, "tamper_probe_failure_count": 1},
        },
    )
    _write_json(
        security / "audit.json",
        {
            "summary": {"PASS": 2, "WARN": 0, "FAIL": 0},
            "findings": [
                {
                    "check": "transport_scheme",
                    "status": "PASS",
                    "evidence": "https://gateway.example/v1",
                    "message": "base_url uses HTTPS",
                }
            ],
        },
    )
    _write_jsonl(
        security / "results.jsonl",
        [
            {"case_id": "case_ok", "category": "stability", "passed": True},
            {"case_id": "case_fail", "category": "security", "passed": False, "error_type": "http_429", "attempts": 2, "error": "HTTP 429"},
        ],
    )
    _write_json(
        benchmark,
        {
            "kind": "benchmark_plan",
            "difficulty": "smoke",
            "suites": [
                {
                    "name": "Terminal-Bench",
                    "benchmark": "terminal-bench",
                    "best_for": "terminal tasks",
                    "recommended_sample_size_per_target": 5,
                    "adapter_status": "external_runner_required",
                }
            ],
        },
    )
    return coding, security, benchmark


def test_render_eval_web_app_embeds_real_artifact_data(tmp_path) -> None:
    coding, security, benchmark = _make_artifacts(tmp_path)
    out = tmp_path / "studio.html"

    rendered = render_eval_web_app(
        coding_run=coding,
        security_run=security,
        benchmark_run=benchmark,
        output_path=out,
        gateway_url="https://gateway.example/v1",
        model="gpt-test",
    )

    text = rendered.read_text(encoding="utf-8")
    assert "LLM Gateway 真实评测工作台" in text
    assert "任务质量" in text
    assert "Terminal-Bench" in text
    assert "task_one" in text
    assert "case_fail" in text


def test_web_report_cli_writes_interactive_html(tmp_path) -> None:
    coding, security, benchmark = _make_artifacts(tmp_path)
    out = tmp_path / "studio.html"

    result = CliRunner().invoke(
        app,
        [
            "web-report",
            "--coding-run",
            str(coding),
            "--security-run",
            str(security),
            "--benchmark-run",
            str(benchmark),
            "--out",
            str(out),
        ],
    )

    assert result.exit_code == 0, result.output
    text = out.read_text(encoding="utf-8")
    assert "const DATA =" in text
    assert "API 错误分布" in text
