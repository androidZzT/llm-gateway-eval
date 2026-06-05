import json

from typer.testing import CliRunner

from llm_gateway_eval.benchmarks import build_benchmark_plan, import_benchmark_results
from llm_gateway_eval.cli import app


def test_build_benchmark_plan_defaults_to_authoritative_coding_suites() -> None:
    plan = build_benchmark_plan(sample_size=12, difficulty="confidence")

    assert plan["kind"] == "benchmark_plan"
    assert plan["status"] == "planned"
    assert [item["benchmark"] for item in plan["suites"]] == [
        "terminal-bench",
        "swe-bench-verified",
        "bfcl",
    ]
    assert plan["suites"][0]["recommended_sample_size_per_target"] == 12
    assert plan["suites"][0]["adapter_status"] == "external_runner_required"


def test_import_benchmark_results_from_jsonl_and_append(tmp_path) -> None:
    official_input = tmp_path / "official.jsonl"
    official_input.write_text(
        json.dumps(
            {
                "task_id": "tb-1",
                "passed": True,
                "duration_seconds": 10,
                "score": 1,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gateway_input = tmp_path / "gateway.jsonl"
    gateway_input.write_text(
        json.dumps(
            {
                "task_id": "tb-1",
                "passed": False,
                "duration_seconds": 15,
                "error": "verification_failed",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    summary = import_benchmark_results(official_input, benchmark="terminal-bench", target="official")
    summary = import_benchmark_results(
        gateway_input,
        benchmark="terminal-bench",
        target="gateway",
        existing_summary=summary,
    )

    by_target = {item["target"]: item for item in summary["targets_summary"]}
    assert summary["kind"] == "benchmark_results"
    assert len(summary["results"]) == 2
    assert by_target["official"]["pass_rate"] == 1
    assert by_target["gateway"]["pass_rate"] == 0
    assert by_target["gateway"]["error_types"] == {"verification_failed": 1}


def test_benchmark_plan_cli_writes_json(tmp_path) -> None:
    out = tmp_path / "plan.json"

    result = CliRunner().invoke(
        app,
        [
            "benchmark-plan",
            "--suite",
            "terminal-bench,bfcl",
            "--sample-size",
            "5",
            "--out",
            str(out),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert [item["benchmark"] for item in payload["suites"]] == ["terminal-bench", "bfcl"]


def test_benchmark_import_cli_appends_existing_summary(tmp_path) -> None:
    out = tmp_path / "summary.json"
    official_input = tmp_path / "official.csv"
    official_input.write_text("task_id,passed,duration_seconds\ntb-1,true,8\n", encoding="utf-8")
    gateway_input = tmp_path / "gateway.csv"
    gateway_input.write_text("task_id,passed,duration_seconds\ntb-1,false,11\n", encoding="utf-8")

    first = CliRunner().invoke(
        app,
        [
            "benchmark-import",
            "--input",
            str(official_input),
            "--benchmark",
            "terminal-bench",
            "--target",
            "official",
            "--out",
            str(out),
        ],
    )
    second = CliRunner().invoke(
        app,
        [
            "benchmark-import",
            "--input",
            str(gateway_input),
            "--benchmark",
            "terminal-bench",
            "--target",
            "gateway",
            "--append",
            "--out",
            str(out),
        ],
    )

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert len(payload["results"]) == 2
    assert {item["target"] for item in payload["targets_summary"]} == {"official", "gateway"}
