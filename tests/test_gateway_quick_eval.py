import json
import os
from pathlib import Path

from typer.testing import CliRunner

from llm_gateway_eval.audit import AuditFinding
from llm_gateway_eval.cli import app
from llm_gateway_eval.models import AssertionResult, RunResult, Usage


def test_gateway_quick_eval_uses_url_key_and_model_without_writing_secret(tmp_path, monkeypatch) -> None:
    project_root = Path(__file__).resolve().parents[1]
    run_dir = tmp_path / "quick-run"
    report_path = tmp_path / "quick-report.md"
    secret = "sk-test-not-written-to-artifacts"
    captured = {}
    monkeypatch.delenv("LLM_GATEWAY_EVAL_GATEWAY_API_KEY", raising=False)

    def fake_audit_config(config, online_tls: bool):
        captured["audit_online_tls"] = online_tls
        return [AuditFinding("gateway", "transport_scheme", "PASS", "base_url uses HTTPS", "https")]

    async def fake_run_evaluation(config, cases):
        captured["config"] = config
        captured["cases"] = list(cases)
        return [
            RunResult(
                case_id="stability_ping_exact",
                category="stability",
                tags=["stability"],
                provider="gateway",
                model="gpt-test",
                output="pong",
                usage=Usage(input_tokens=7, output_tokens=3, total_tokens=10),
                latency_seconds=0.2,
                ttft_seconds=None,
                error=None,
                attempts=1,
                assertion_results=[AssertionResult(type="equals", passed=True, message="ok")],
                cost=0.0,
                currency="CNY",
                requested_model="gpt-test",
            )
        ]

    monkeypatch.setattr("llm_gateway_eval.cli.audit_config", fake_audit_config)
    monkeypatch.setattr("llm_gateway_eval.cli.run_evaluation", fake_run_evaluation)

    result = CliRunner().invoke(
        app,
        [
            "gateway-quick-eval",
            "--gateway-url",
            "https://gateway.example.com/v1",
            "--gateway-api-key",
            secret,
            "--model",
            "gpt-test",
            "--cases",
            str(project_root / "data" / "cases" / "gateway_core.jsonl"),
            "--out",
            str(run_dir),
            "--report-out",
            str(report_path),
            "--repeats",
            "2",
            "--attempts",
            "3",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["audit_online_tls"] is True
    assert len(captured["cases"]) == 16
    assert any("dynamic_security_probe" in case.tags for case in captured["cases"])
    assert captured["config"].run.repeat_per_case == 2
    assert captured["config"].run.attempts == 3
    assert captured["config"].targets[0].name == "gateway"
    assert captured["config"].targets[0].api_key_env == "LLM_GATEWAY_EVAL_GATEWAY_API_KEY"

    artifact_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            run_dir / "quick_config.json",
            run_dir / "audit.json",
            run_dir / "security_probes.json",
            run_dir / "results.jsonl",
            run_dir / "summary.json",
            report_path,
        ]
    )
    assert secret not in artifact_text
    assert "Transport and Privacy Configuration Audit" in report_path.read_text(encoding="utf-8")
    assert "Tamper and Canary Analysis" in report_path.read_text(encoding="utf-8")
    assert "Usage and Billing Accuracy" in report_path.read_text(encoding="utf-8")
    assert "Routing and Degradation Signals" in report_path.read_text(encoding="utf-8")
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert "usage_billing_analysis" in summary
    assert "routing_degradation_analysis" in summary
    assert "LLM_GATEWAY_EVAL_GATEWAY_API_KEY" not in os.environ


def test_gateway_quick_eval_adds_external_honeytoken_and_imports_events(tmp_path, monkeypatch) -> None:
    project_root = Path(__file__).resolve().parents[1]
    run_dir = tmp_path / "quick-run"
    report_path = tmp_path / "quick-report.md"
    captured = {}
    monkeypatch.setenv("GATEWAY_API_KEY", "gateway-key")

    monkeypatch.setattr(
        "llm_gateway_eval.cli.audit_config",
        lambda config, online_tls: [
            AuditFinding("gateway", "transport_scheme", "PASS", "base_url uses HTTPS", "https")
        ],
    )

    async def fake_run_evaluation(config, cases):
        captured["cases"] = list(cases)
        return [
            RunResult(
                case_id="stability_ping_exact",
                category="stability",
                tags=["stability"],
                provider="gateway",
                model="gpt-test",
                output="pong",
                usage=Usage(input_tokens=7, output_tokens=3, total_tokens=10),
                latency_seconds=0.2,
                ttft_seconds=None,
                error=None,
                attempts=1,
                assertion_results=[AssertionResult(type="equals", passed=True, message="ok")],
                cost=0.0,
                currency="CNY",
                requested_model="gpt-test",
            )
        ]

    monkeypatch.setattr("llm_gateway_eval.cli.run_evaluation", fake_run_evaluation)

    result = CliRunner().invoke(
        app,
        [
            "gateway-quick-eval",
            "--gateway-url",
            "https://gateway.example.com/v1",
            "--model",
            "gpt-test",
            "--cases",
            str(project_root / "data" / "cases" / "gateway_core.jsonl"),
            "--out",
            str(run_dir),
            "--report-out",
            str(report_path),
            "--no-online-tls",
            "--honeytoken-base-url",
            "https://webhook.example/hook",
        ],
    )

    assert result.exit_code == 0, result.output
    assert any("honeytoken" in case.tags for case in captured["cases"])
    probe_payload = json.loads((run_dir / "security_probes.json").read_text(encoding="utf-8"))
    honeytoken_url = probe_payload["honeytokens"][0]["value"]
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["security_analysis"]["honeytoken_count"] == 1
    assert summary["security_analysis"]["external_honeytoken_event_count"] is None

    events_path = tmp_path / "events.jsonl"
    events_path.write_text(json.dumps({"url": honeytoken_url}) + "\n", encoding="utf-8")
    updated_report = tmp_path / "updated-report.md"
    event_result = CliRunner().invoke(
        app,
        [
            "honeytoken-events",
            str(run_dir),
            "--events",
            str(events_path),
            "--report-out",
            str(updated_report),
        ],
    )

    assert event_result.exit_code == 0, event_result.output
    updated_summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert updated_summary["security_analysis"]["external_honeytoken_event_count"] == 1
    rendered = updated_report.read_text(encoding="utf-8")
    assert "External Honeytoken Hits" in rendered
    assert "[HONEYTOKEN:external_fetch_url]" in rendered
    assert honeytoken_url not in rendered


def test_gateway_quick_eval_adds_optional_official_baseline(tmp_path, monkeypatch) -> None:
    project_root = Path(__file__).resolve().parents[1]
    run_dir = tmp_path / "quick-run"
    monkeypatch.setenv("GATEWAY_API_KEY", "gateway-key")
    monkeypatch.setenv("OPENAI_API_KEY", "official-key")
    captured = {}

    monkeypatch.setattr(
        "llm_gateway_eval.cli.audit_config",
        lambda config, online_tls: [
            AuditFinding(target.name, "transport_scheme", "PASS", "base_url uses HTTPS", target.base_url)
            for target in config.targets
        ],
    )

    async def fake_run_evaluation(config, cases):
        captured["config"] = config
        return [
            RunResult(
                case_id="case",
                category="model_authenticity",
                tags=["authenticity"],
                provider=target.name,
                model="gpt-test",
                output="ok",
                usage=Usage(input_tokens=1, output_tokens=1, total_tokens=2),
                latency_seconds=0.1,
                ttft_seconds=None,
                error=None,
                attempts=1,
                assertion_results=[AssertionResult(type="contains", passed=True, message="ok")],
                cost=0.0,
                currency="CNY",
                requested_model="gpt-test",
            )
            for target in config.targets
        ]

    monkeypatch.setattr("llm_gateway_eval.cli.run_evaluation", fake_run_evaluation)

    result = CliRunner().invoke(
        app,
        [
            "gateway-quick-eval",
            "--gateway-url",
            "https://gateway.example.com/v1",
            "--model",
            "gpt-test",
            "--official-url",
            "https://api.openai.com/v1",
            "--official-api-key-env",
            "OPENAI_API_KEY",
            "--cases",
            str(project_root / "data" / "cases" / "gateway_core.jsonl"),
            "--out",
            str(run_dir),
            "--report-out",
            str(tmp_path / "quick-report.md"),
            "--no-online-tls",
        ],
    )

    assert result.exit_code == 0, result.output
    assert [target.name for target in captured["config"].targets] == ["official", "gateway"]
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["quick_eval"]["official_baseline_enabled"] is True
    assert set(summary["providers"]) == {"official", "gateway"}


def test_gateway_quick_eval_detects_input_usage_anomaly(tmp_path, monkeypatch) -> None:
    project_root = Path(__file__).resolve().parents[1]
    run_dir = tmp_path / "quick-run"
    monkeypatch.setenv("GATEWAY_API_KEY", "gateway-key")
    monkeypatch.setenv("OPENAI_API_KEY", "official-key")

    monkeypatch.setattr(
        "llm_gateway_eval.cli.audit_config",
        lambda config, online_tls: [
            AuditFinding(target.name, "transport_scheme", "PASS", "base_url uses HTTPS", target.base_url)
            for target in config.targets
        ],
    )

    async def fake_run_evaluation(config, cases):
        case = list(cases)[0]
        return [
            RunResult(
                case_id=case.id,
                category=case.category,
                tags=case.tags,
                provider="official",
                model="gpt-test",
                output="ok",
                usage=Usage(input_tokens=100, output_tokens=10, total_tokens=110),
                latency_seconds=0.1,
                ttft_seconds=None,
                error=None,
                attempts=1,
                assertion_results=[AssertionResult(type="contains", passed=True, message="ok")],
                cost=0.0,
                currency="CNY",
                requested_model="gpt-test",
                repeat_index=1,
            ),
            RunResult(
                case_id=case.id,
                category=case.category,
                tags=case.tags,
                provider="gateway",
                model="gpt-test",
                output="ok",
                usage=Usage(input_tokens=180, output_tokens=10, total_tokens=190),
                latency_seconds=0.1,
                ttft_seconds=None,
                error=None,
                attempts=1,
                assertion_results=[AssertionResult(type="contains", passed=True, message="ok")],
                cost=0.0,
                currency="CNY",
                requested_model="gpt-test",
                repeat_index=1,
            ),
        ]

    monkeypatch.setattr("llm_gateway_eval.cli.run_evaluation", fake_run_evaluation)

    result = CliRunner().invoke(
        app,
        [
            "gateway-quick-eval",
            "--gateway-url",
            "https://gateway.example.com/v1",
            "--model",
            "gpt-test",
            "--official-url",
            "https://api.openai.com/v1",
            "--official-api-key-env",
            "OPENAI_API_KEY",
            "--cases",
            str(project_root / "data" / "cases" / "gateway_core.jsonl"),
            "--out",
            str(run_dir),
            "--report-out",
            str(tmp_path / "quick-report.md"),
            "--no-online-tls",
        ],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["security_analysis"]["usage_anomaly_count"] == 1
    assert summary["usage_billing_analysis"]["paired_usage_discrepancy_count"] >= 1
    anomaly = summary["security_analysis"]["usage_anomalies"][0]
    assert anomaly["provider"] == "gateway"
    assert anomaly["ratio"] == 1.8
