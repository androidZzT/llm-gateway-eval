from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from .agent_compare import (
    AgentCompareError,
    build_claude_agent_target,
    build_codex_agent_target,
    discover_agent_tasks,
    run_agent_compare,
    write_agent_compare_outputs,
)
from .agent_report import render_agent_compare_report
from .audit import audit_config
from .billing import analyze_usage_billing
from .benchmarks import (
    SUPPORTED_BENCHMARKS,
    BenchmarkError,
    build_benchmark_plan,
    import_benchmark_results,
    parse_suite_csv,
)
from .cases import CaseError, load_cases
from .codex_compare import (
    CodexCompareError,
    CodexCompareTarget,
    discover_tasks,
    run_codex_compare,
    write_codex_compare_outputs,
)
from .config import ConfigError, load_config, validate_config_env
from .honeytokens import (
    analyze_honeytoken_events,
    apply_honeytoken_analysis_to_summary,
    load_honeytoken_event_records,
)
from .metrics import aggregate_results
from .models import EvalConfig, Pricing, ProviderTarget, ReportOptions, RunOptions
from .pricing import TokenPricing, official_pricing_for_model, scaled_pricing
from .report import render_report
from .routing import analyze_routing_degradation
from .runner import run_evaluation
from .security import analyze_security_results, build_security_probe_bundle
from .web_app import render_eval_web_app
from .web_server import serve_gateway_eval_web
from .weytoken_pricing import (
    DEFAULT_USD_CNY_RATE,
    WeyTokenPricingError,
    build_weytoken_price_rows,
    fetch_weytoken_pricing,
    is_weytoken_url,
    load_official_price_file,
    price_for_model,
    write_weytoken_pricing_outputs,
)


app = typer.Typer(no_args_is_help=True, help="Evaluate OpenAI-compatible LLM gateways.")

QUICK_GATEWAY_API_KEY_ENV = "LLM_GATEWAY_EVAL_GATEWAY_API_KEY"
QUICK_OFFICIAL_API_KEY_ENV = "LLM_GATEWAY_EVAL_OFFICIAL_API_KEY"
QUICK_CLAUDE_GATEWAY_API_KEY_ENV = "LLM_GATEWAY_EVAL_CLAUDE_GATEWAY_API_KEY"


@app.command()
def validate(
    config: Annotated[Path, typer.Option("--config", "-c", help="Evaluation YAML config.")],
    cases: Annotated[Path, typer.Option("--cases", help="JSONL eval cases.")],
) -> None:
    """Validate config, API key env vars, and case file shape."""
    try:
        eval_config = load_config(config)
        validate_config_env(eval_config)
        eval_cases = load_cases(cases)
    except (ConfigError, CaseError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.echo(f"OK: {len(eval_config.targets)} target(s), {len(eval_cases)} case(s).")


@app.command("run")
def run_command(
    config: Annotated[Path, typer.Option("--config", "-c", help="Evaluation YAML config.")],
    cases: Annotated[Path, typer.Option("--cases", help="JSONL eval cases.")],
    out: Annotated[Path, typer.Option("--out", help="Output run directory.")],
) -> None:
    """Run eval cases and write results.jsonl plus summary.json."""
    try:
        eval_config = load_config(config)
        validate_config_env(eval_config)
        eval_cases = load_cases(cases)
    except (ConfigError, CaseError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.echo(f"Running {len(eval_cases)} case(s) against {len(eval_config.targets)} target(s)...")
    results = asyncio.run(run_evaluation(eval_config, eval_cases))
    summary = aggregate_results(eval_config, results)
    summary["config_path"] = str(config)
    summary["cases_path"] = str(cases)
    summary["usage_billing_analysis"] = analyze_usage_billing(eval_config, eval_cases, results)
    summary["routing_degradation_analysis"] = analyze_routing_degradation(results)

    out.mkdir(parents=True, exist_ok=True)
    results_path = out / "results.jsonl"
    summary_path = out / "summary.json"
    results_path.write_text(
        "\n".join(json.dumps(result.to_dict(), ensure_ascii=False) for result in results) + "\n",
        encoding="utf-8",
    )
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    typer.echo(f"Wrote {results_path}")
    typer.echo(f"Wrote {summary_path}")


@app.command()
def report(
    run_dir: Annotated[Path, typer.Argument(help="Directory containing results.jsonl and summary.json.")],
    out: Annotated[Path, typer.Option("--out", help="Markdown report output path.")],
    template: Annotated[Path | None, typer.Option("--template", help="Optional Jinja2 report template.")] = None,
) -> None:
    """Render a Markdown report from a completed run directory."""
    rendered = render_report(run_dir, out, template)
    typer.echo(f"Wrote {rendered}")


@app.command("benchmark-plan")
def benchmark_plan_command(
    out: Annotated[
        Path,
        typer.Option("--out", help="Benchmark plan JSON output path."),
    ] = Path("runs/benchmark-plan.json"),
    suites: Annotated[
        str,
        typer.Option(
            "--suite",
            help="Comma-separated benchmark suites. Supported: "
            + ", ".join(sorted(SUPPORTED_BENCHMARKS)),
        ),
    ] = "terminal-bench,swe-bench-verified,bfcl",
    sample_size: Annotated[
        int,
        typer.Option("--sample-size", min=1, help="Recommended sampled task count per target."),
    ] = 20,
    difficulty: Annotated[
        str,
        typer.Option("--difficulty", help="Plan level: smoke, confidence, hard, or full."),
    ] = "smoke",
) -> None:
    """Write a reusable plan for authoritative external benchmark runs."""
    try:
        plan = build_benchmark_plan(parse_suite_csv(suites), sample_size=sample_size, difficulty=difficulty)
    except BenchmarkError as exc:
        raise typer.BadParameter(str(exc)) from exc

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    typer.echo(f"Wrote {out}")
    typer.echo("Suites: " + ", ".join(item["benchmark"] for item in plan["suites"]))


@app.command("benchmark-import")
def benchmark_import_command(
    input_path: Annotated[
        Path,
        typer.Option("--input", "-i", help="External benchmark result JSON, JSONL, CSV, or directory."),
    ],
    benchmark: Annotated[
        str,
        typer.Option("--benchmark", help="Benchmark suite id, for example terminal-bench or swe-bench-verified."),
    ],
    out: Annotated[
        Path,
        typer.Option("--out", help="Normalized benchmark summary JSON output path."),
    ] = Path("runs/benchmark-results/summary.json"),
    target: Annotated[
        str | None,
        typer.Option("--target", help="Target name to apply when rows do not include target/provider."),
    ] = None,
    append: Annotated[
        bool,
        typer.Option("--append/--no-append", help="Append to an existing normalized summary at --out."),
    ] = False,
) -> None:
    """Normalize external benchmark task results for HTML reporting."""
    try:
        existing = json.loads(out.read_text(encoding="utf-8")) if append and out.exists() else None
        summary = import_benchmark_results(
            input_path,
            benchmark=benchmark,
            target=target,
            existing_summary=existing,
        )
    except (BenchmarkError, OSError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    typer.echo(f"Imported {len(summary['results'])} normalized benchmark row(s).")
    typer.echo(f"Wrote {out}")


@app.command("web-report")
def web_report_command(
    coding_run: Annotated[
        Path,
        typer.Option("--coding-run", help="Run dir from codex-quick-compare."),
    ],
    security_run: Annotated[
        Path,
        typer.Option("--security-run", help="Run dir from gateway-quick-eval."),
    ],
    out: Annotated[
        Path,
        typer.Option("--out", help="Interactive HTML web report output path."),
    ],
    benchmark_run: Annotated[
        Path | None,
        typer.Option("--benchmark-run", help="Optional benchmark plan/result JSON or summary directory."),
    ] = None,
    gateway_url: Annotated[str, typer.Option("--gateway-url", help="Gateway URL shown in the web report.")] = "",
    model: Annotated[str, typer.Option("--model", help="Model name shown in the web report.")] = "",
    title: Annotated[str, typer.Option("--title", help="Page title.")] = "LLM Gateway 真实评测工作台",
) -> None:
    """Render an interactive static HTML web app from real eval artifacts."""
    try:
        rendered = render_eval_web_app(
            coding_run=coding_run,
            security_run=security_run,
            benchmark_run=benchmark_run,
            gateway_url=gateway_url,
            model=model,
            output_path=out,
            title=title,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Wrote {rendered}")


@app.command("serve")
def serve_command(
    host: Annotated[str, typer.Option("--host", help="Host for the local web evaluator.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", min=1, max=65535, help="Port for the local web evaluator.")] = 8787,
    project_root: Annotated[
        Path,
        typer.Option("--project-root", help="llm-gateway-eval project root."),
    ] = Path("."),
) -> None:
    """Start a local website for evaluating gateway API quality."""
    serve_gateway_eval_web(host=host, port=port, project_root=project_root.resolve())


@app.command("honeytoken-events")
def honeytoken_events_command(
    run_dir: Annotated[Path, typer.Argument(help="Directory containing security_probes.json and summary.json.")],
    events: Annotated[
        Path,
        typer.Option("--events", help="Webhook/honeytoken event export as JSON, JSONL, or plain text."),
    ],
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Optional analysis output path. Defaults to RUN_DIR/honeytoken_events.json."),
    ] = None,
    report_out: Annotated[
        Path | None,
        typer.Option("--report-out", help="Optional Markdown report path to render after updating summary."),
    ] = None,
    template: Annotated[Path | None, typer.Option("--template", help="Optional Jinja2 report template.")] = None,
) -> None:
    """Import external honeytoken events and update a completed quick-eval summary."""
    probes_path = run_dir / "security_probes.json"
    summary_path = run_dir / "summary.json"
    if not probes_path.exists():
        raise typer.BadParameter(f"missing {probes_path}")
    if not summary_path.exists():
        raise typer.BadParameter(f"missing {summary_path}")
    if not events.exists():
        raise typer.BadParameter(f"missing {events}")

    probe_payload = json.loads(probes_path.read_text(encoding="utf-8"))
    records = load_honeytoken_event_records(events)
    analysis = analyze_honeytoken_events(probe_payload, records, events)

    output_path = out or (run_dir / "honeytoken_events.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(analysis.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    updated_summary = apply_honeytoken_analysis_to_summary(summary, analysis, output_path)
    summary_path.write_text(json.dumps(updated_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    typer.echo(f"Wrote {output_path}")
    typer.echo(f"Updated {summary_path}")
    if report_out is not None:
        rendered = render_report(run_dir, report_out, template)
        typer.echo(f"Wrote {rendered}")


@app.command()
def audit(
    config: Annotated[Path, typer.Option("--config", "-c", help="Evaluation YAML config.")],
    online_tls: Annotated[bool, typer.Option("--online-tls", help="Perform live TLS handshake checks.")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print findings as JSON.")] = False,
    fail_on_finding: Annotated[
        bool,
        typer.Option("--fail-on-finding", help="Exit nonzero when WARN or FAIL findings exist."),
    ] = False,
) -> None:
    """Audit transport security and obvious secret-handling risks in config."""
    try:
        eval_config = load_config(config)
    except ConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc

    findings = audit_config(eval_config, online_tls=online_tls)
    if json_output:
        typer.echo(json.dumps([finding.to_dict() for finding in findings], ensure_ascii=False, indent=2))
    else:
        for finding in findings:
            evidence = f" ({finding.evidence})" if finding.evidence else ""
            typer.echo(f"[{finding.status}] {finding.target} {finding.check}: {finding.message}{evidence}")

    if fail_on_finding and any(finding.status in {"WARN", "FAIL"} for finding in findings):
        raise typer.Exit(2)


@app.command("gateway-quick-eval")
def gateway_quick_eval_command(
    gateway_url: Annotated[
        str,
        typer.Option("--gateway-url", help="Gateway base URL, for example https://gateway.example.com/v1."),
    ],
    model: Annotated[str, typer.Option("--model", help="Requested model name.")],
    gateway_api_key: Annotated[
        str | None,
        typer.Option("--gateway-api-key", help="Gateway API key. It is used only in-process and never written."),
    ] = None,
    gateway_api_key_env: Annotated[
        str,
        typer.Option("--gateway-api-key-env", help="Environment variable containing the gateway API key."),
    ] = "GATEWAY_API_KEY",
    official_url: Annotated[
        str | None,
        typer.Option("--official-url", help="Optional direct-provider baseline base URL."),
    ] = None,
    official_api_key: Annotated[
        str | None,
        typer.Option("--official-api-key", help="Official baseline API key. It is used only in-process."),
    ] = None,
    official_api_key_env: Annotated[
        str,
        typer.Option("--official-api-key-env", help="Environment variable containing the official baseline API key."),
    ] = "OFFICIAL_API_KEY",
    cases: Annotated[
        Path,
        typer.Option("--cases", help="JSONL eval cases."),
    ] = Path("data/cases/gateway_core.jsonl"),
    out: Annotated[
        Path,
        typer.Option("--out", help="Output run directory."),
    ] = Path("runs/gateway-quick-eval"),
    report_out: Annotated[
        Path | None,
        typer.Option("--report-out", help="Optional Markdown report output path."),
    ] = Path("reports/gateway-quick-eval.md"),
    repeats: Annotated[int, typer.Option("--repeats", min=1, help="Repeats per case.")] = 3,
    attempts: Annotated[int, typer.Option("--attempts", min=1, help="Retry attempts per request.")] = 2,
    concurrency: Annotated[int, typer.Option("--concurrency", min=1, help="Concurrent requests.")] = 2,
    timeout_seconds: Annotated[
        float,
        typer.Option("--timeout-seconds", min=1, help="Request timeout in seconds."),
    ] = 60.0,
    temperature: Annotated[float, typer.Option("--temperature", help="Sampling temperature.")] = 0.0,
    max_tokens: Annotated[int, typer.Option("--max-tokens", min=1, help="Maximum output tokens.")] = 1024,
    stream: Annotated[bool, typer.Option("--stream/--no-stream", help="Use streaming chat completions.")] = False,
    online_tls: Annotated[
        bool,
        typer.Option("--online-tls/--no-online-tls", help="Perform live TLS handshake checks before running cases."),
    ] = True,
    fail_on_audit: Annotated[
        bool,
        typer.Option("--fail-on-audit", help="Stop before model requests when audit has WARN or FAIL findings."),
    ] = False,
    dynamic_security_probes: Annotated[
        bool,
        typer.Option("--dynamic-security-probes/--no-dynamic-security-probes", help="Add per-run canary and tamper probes."),
    ] = True,
    honeytoken_base_url: Annotated[
        str | None,
        typer.Option(
            "--honeytoken-base-url",
            help="Optional webhook/canary base URL for out-of-band egress monitoring.",
        ),
    ] = None,
) -> None:
    """Run the core gateway eval with only URL, key, and model."""
    env_restore: list[tuple[str, str | None]] = []
    try:
        gateway_key_env = _resolve_quick_api_key_env(
            direct_key=gateway_api_key,
            configured_env=gateway_api_key_env,
            temp_env=QUICK_GATEWAY_API_KEY_ENV,
            label="gateway",
            option_name="--gateway-api-key",
            env_restore=env_restore,
        )
        if official_api_key and not official_url:
            raise typer.BadParameter("--official-api-key requires --official-url.")

        official_key_env: str | None = None
        if official_url:
            official_key_env = _resolve_quick_api_key_env(
                direct_key=official_api_key,
                configured_env=official_api_key_env,
                temp_env=QUICK_OFFICIAL_API_KEY_ENV,
                label="official baseline",
                option_name="--official-api-key",
                env_restore=env_restore,
            )

        eval_config = _build_quick_eval_config(
            gateway_url=gateway_url,
            gateway_api_key_env=gateway_key_env,
            model=model,
            official_url=official_url,
            official_api_key_env=official_key_env,
            repeats=repeats,
            attempts=attempts,
            concurrency=concurrency,
            timeout_seconds=timeout_seconds,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
        )
        try:
            eval_cases = load_cases(cases)
        except CaseError as exc:
            raise typer.BadParameter(str(exc)) from exc
        if honeytoken_base_url and not dynamic_security_probes:
            raise typer.BadParameter("--honeytoken-base-url requires --dynamic-security-probes.")
        try:
            security_probe_bundle = (
                build_security_probe_bundle(honeytoken_base_url=honeytoken_base_url)
                if dynamic_security_probes
                else None
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        if security_probe_bundle is not None:
            eval_cases = [*eval_cases, *security_probe_bundle.cases]

        out.mkdir(parents=True, exist_ok=True)
        quick_config_path = out / "quick_config.json"
        audit_path = out / "audit.json"
        security_probes_path = out / "security_probes.json"
        results_path = out / "results.jsonl"
        summary_path = out / "summary.json"

        quick_config_path.write_text(
            json.dumps(asdict(eval_config), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        findings = audit_config(eval_config, online_tls=online_tls)
        audit_payload = {
            "online_tls": online_tls,
            "summary": _summarise_audit_findings(findings),
            "findings": [finding.to_dict() for finding in findings],
        }
        audit_path.write_text(json.dumps(audit_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        typer.echo(f"Wrote {audit_path}")
        if security_probe_bundle is not None:
            security_probes_path.write_text(
                json.dumps(security_probe_bundle.to_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            typer.echo(f"Wrote {security_probes_path}")

        if fail_on_audit and any(finding.status in {"WARN", "FAIL"} for finding in findings):
            typer.echo("Audit found WARN/FAIL findings; stopped before sending model requests.", err=True)
            raise typer.Exit(2)

        typer.echo(
            f"Running {len(eval_cases)} case(s) against {len(eval_config.targets)} target(s) "
            f"x {repeats} repeat(s)..."
        )
        results = asyncio.run(run_evaluation(eval_config, eval_cases))
        summary = aggregate_results(eval_config, results)
        summary["config_path"] = str(quick_config_path)
        summary["cases_path"] = str(cases)
        summary["quick_eval"] = {
            "gateway_url": gateway_url.rstrip("/"),
            "model": model,
            "official_baseline_enabled": official_url is not None,
            "official_url": official_url.rstrip("/") if official_url else None,
            "report_scope": (
                "transport audit, model authenticity probes, privacy/security cases, "
                "dynamic canaries, tamper probes, stability repeats"
                + (", external honeytoken egress probe" if honeytoken_base_url else "")
            ),
            "external_honeytoken_enabled": honeytoken_base_url is not None,
        }
        summary["audit"] = audit_payload["summary"]
        summary["audit_path"] = str(audit_path)
        summary["audit_findings"] = audit_payload["findings"]
        summary["security_probes_path"] = str(security_probes_path) if security_probe_bundle is not None else None
        summary["security_analysis"] = analyze_security_results(results, security_probe_bundle)
        summary["usage_billing_analysis"] = analyze_usage_billing(eval_config, eval_cases, results)
        summary["routing_degradation_analysis"] = analyze_routing_degradation(results)

        results_path.write_text(
            "\n".join(json.dumps(result.to_dict(), ensure_ascii=False) for result in results) + "\n",
            encoding="utf-8",
        )
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        typer.echo(f"Wrote {quick_config_path}")
        typer.echo(f"Wrote {results_path}")
        typer.echo(f"Wrote {summary_path}")

        if report_out is not None:
            rendered = render_report(out, report_out)
            typer.echo(f"Wrote {rendered}")
    finally:
        _restore_env_vars(env_restore)


def _resolve_quick_api_key_env(
    direct_key: str | None,
    configured_env: str,
    temp_env: str,
    label: str,
    option_name: str,
    env_restore: list[tuple[str, str | None]],
) -> str:
    if direct_key:
        env_restore.append((temp_env, os.environ.get(temp_env)))
        os.environ[temp_env] = direct_key
        return temp_env
    if not os.getenv(configured_env):
        raise typer.BadParameter(
            f"Missing {label} API key. Pass {option_name} or set {configured_env}."
        )
    return configured_env


def _restore_env_vars(env_restore: list[tuple[str, str | None]]) -> None:
    for name, previous_value in reversed(env_restore):
        if previous_value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous_value


def _build_quick_eval_config(
    gateway_url: str,
    gateway_api_key_env: str,
    model: str,
    official_url: str | None,
    official_api_key_env: str | None,
    repeats: int,
    attempts: int,
    concurrency: int,
    timeout_seconds: float,
    temperature: float,
    max_tokens: int,
    stream: bool,
) -> EvalConfig:
    params = {"temperature": temperature, "max_tokens": max_tokens}
    targets: list[ProviderTarget] = []
    if official_url and official_api_key_env:
        targets.append(
            ProviderTarget(
                name="official",
                base_url=official_url.rstrip("/"),
                api_key_env=official_api_key_env,
                model=model,
                params=dict(params),
                pricing=Pricing(currency="CNY"),
            )
        )
    targets.append(
        ProviderTarget(
            name="gateway",
            base_url=gateway_url.rstrip("/"),
            api_key_env=gateway_api_key_env,
            model=model,
            params=dict(params),
            pricing=Pricing(currency="CNY"),
        )
    )
    return EvalConfig(
        run=RunOptions(
            timeout_seconds=timeout_seconds,
            concurrency=concurrency,
            attempts=attempts,
            repeat_per_case=repeats,
            stream=stream,
            performance_targets={"p95_latency_seconds": 8},
        ),
        targets=targets,
        report=ReportOptions(title=f"Gateway Quick Evaluation: {model}"),
    )


def _summarise_audit_findings(findings) -> dict[str, int]:
    summary = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for finding in findings:
        if finding.status in summary:
            summary[finding.status] += 1
    summary["total"] = len(findings)
    return summary


@app.command("codex-compare")
def codex_compare_command(
    tasks: Annotated[Path, typer.Option("--tasks", help="Directory containing task subdirectories.")],
    official_profile: Annotated[str, typer.Option("--official-profile", help="Codex profile for official baseline.")],
    gateway_profile: Annotated[str, typer.Option("--gateway-profile", help="Codex profile for gateway under test.")],
    out: Annotated[Path, typer.Option("--out", help="Output comparison directory.")],
    repeats: Annotated[int, typer.Option("--repeats", min=1, help="Repeats per task per target.")] = 3,
    codex_bin: Annotated[str, typer.Option("--codex-bin", help="Codex executable path/name.")] = "codex",
    prompt_file: Annotated[str, typer.Option("--prompt-file", help="Task prompt filename.")] = "TASK.md",
    verify_command: Annotated[str, typer.Option("--verify-command", help="Command to verify a completed task.")] = "bash ./verify.sh",
    timeout_seconds: Annotated[int, typer.Option("--timeout-seconds", min=1, help="Timeout for Codex and verify commands.")] = 1800,
    report_out: Annotated[Path | None, typer.Option("--report-out", help="Optional Markdown report output path.")] = None,
) -> None:
    """Run paired Codex official-vs-gateway coding-agent tasks."""
    try:
        codex_tasks = discover_tasks(tasks, prompt_file=prompt_file, verify_command=verify_command)
    except CodexCompareError as exc:
        raise typer.BadParameter(str(exc)) from exc

    targets = [
        CodexCompareTarget(name="official", profile=official_profile),
        CodexCompareTarget(name="gateway", profile=gateway_profile),
    ]
    typer.echo(f"Running {len(codex_tasks)} task(s) x {len(targets)} target(s) x {repeats} repeat(s)...")
    results, summary = run_codex_compare(
        tasks=codex_tasks,
        targets=targets,
        repeats=repeats,
        out_dir=out,
        codex_bin=codex_bin,
        timeout_seconds=timeout_seconds,
    )
    summary["tasks_path"] = str(tasks)
    results_path, summary_path = write_codex_compare_outputs(results, summary, out)
    typer.echo(f"Wrote {results_path}")
    typer.echo(f"Wrote {summary_path}")

    if report_out is not None:
        from .codex_report import render_codex_compare_report

        rendered = render_codex_compare_report(out, report_out)
        typer.echo(f"Wrote {rendered}")


@app.command("codex-quick-compare")
def codex_quick_compare_command(
    gateway_url: Annotated[str, typer.Option("--gateway-url", help="Gateway base URL, for example https://gateway.example.com/v1.")],
    tasks: Annotated[Path, typer.Option("--tasks", help="Directory containing task subdirectories.")] = Path("data/codex_tasks"),
    out: Annotated[Path, typer.Option("--out", help="Output comparison directory.")] = Path("runs/codex-gateway"),
    gateway_api_key: Annotated[
        str | None,
        typer.Option("--gateway-api-key", help="Gateway API key. Prefer --gateway-api-key-env for shared shells."),
    ] = None,
    gateway_api_key_env: Annotated[
        str,
        typer.Option("--gateway-api-key-env", help="Environment variable containing the gateway API key."),
    ] = "GATEWAY_API_KEY",
    model: Annotated[
        str | None,
        typer.Option("--model", help="Optional model override applied to both official and gateway runs."),
    ] = None,
    official_input_price: Annotated[
        float | None,
        typer.Option("--official-input-price", help="Official input price per 1M tokens."),
    ] = None,
    official_cached_input_price: Annotated[
        float | None,
        typer.Option("--official-cached-input-price", help="Official cached-input price per 1M tokens."),
    ] = None,
    official_output_price: Annotated[
        float | None,
        typer.Option("--official-output-price", help="Official output price per 1M tokens."),
    ] = None,
    gateway_input_price: Annotated[
        float | None,
        typer.Option("--gateway-input-price", help="Gateway input price per 1M tokens."),
    ] = None,
    gateway_cached_input_price: Annotated[
        float | None,
        typer.Option("--gateway-cached-input-price", help="Gateway cached-input price per 1M tokens."),
    ] = None,
    gateway_output_price: Annotated[
        float | None,
        typer.Option("--gateway-output-price", help="Gateway output price per 1M tokens."),
    ] = None,
    gateway_price_multiplier: Annotated[
        float | None,
        typer.Option("--gateway-price-multiplier", help="Gateway price as a multiplier of official price."),
    ] = None,
    gateway_pricing_group: Annotated[
        str,
        typer.Option("--gateway-pricing-group", help="WeyToken pricing group, or best for lowest enabled group."),
    ] = "best",
    no_auto_gateway_price: Annotated[
        bool,
        typer.Option("--no-auto-gateway-price", help="Disable automatic WeyToken pricing lookup."),
    ] = False,
    currency: Annotated[str, typer.Option("--currency", help="Currency for price comparison.")] = "USD",
    wire_api: Annotated[str, typer.Option("--wire-api", help="Codex provider wire API for the gateway.")] = "responses",
    repeats: Annotated[int, typer.Option("--repeats", min=1, help="Repeats per task per target.")] = 3,
    codex_bin: Annotated[str, typer.Option("--codex-bin", help="Codex executable path/name.")] = "codex",
    timeout_seconds: Annotated[int, typer.Option("--timeout-seconds", min=1, help="Timeout for Codex and verify commands.")] = 1800,
    report_out: Annotated[Path, typer.Option("--report-out", help="Markdown report output path.")] = Path("reports/codex-gateway.md"),
) -> None:
    """Compare current official Codex config against a gateway using only URL and key."""
    try:
        codex_tasks = discover_tasks(tasks)
    except CodexCompareError as exc:
        raise typer.BadParameter(str(exc)) from exc

    key_env_for_codex = gateway_api_key_env
    gateway_env: dict[str, str] = {}
    if gateway_api_key:
        key_env_for_codex = "LLM_GATEWAY_EVAL_CODEX_GATEWAY_API_KEY"
        gateway_env[key_env_for_codex] = gateway_api_key
    elif not os.getenv(gateway_api_key_env):
        raise typer.BadParameter(
            f"Missing gateway API key. Pass --gateway-api-key or set {gateway_api_key_env}."
        )

    common_overrides = ['web_search="disabled"']
    if model:
        common_overrides.append(f"model={_toml_string(model)}")

    gateway_overrides = [
        *common_overrides,
        'model_provider="gateway_quick"',
        'model_providers.gateway_quick.name="Gateway under test"',
        f"model_providers.gateway_quick.base_url={_toml_string(gateway_url.rstrip('/'))}",
        f"model_providers.gateway_quick.env_key={_toml_string(key_env_for_codex)}",
    ]
    if wire_api:
        gateway_overrides.append(f"model_providers.gateway_quick.wire_api={_toml_string(wire_api)}")

    official_pricing = _resolve_official_pricing(
        model=model,
        input_price=official_input_price,
        cached_input_price=official_cached_input_price,
        output_price=official_output_price,
        currency=currency,
    )
    gateway_pricing = _resolve_gateway_pricing(
        official_pricing=official_pricing,
        input_price=gateway_input_price,
        cached_input_price=gateway_cached_input_price,
        output_price=gateway_output_price,
        multiplier=gateway_price_multiplier,
        currency=currency,
    )
    if gateway_pricing is None and model and not no_auto_gateway_price and is_weytoken_url(gateway_url):
        try:
            gateway_pricing = price_for_model(gateway_url, model=model, group=gateway_pricing_group, currency=currency)
        except Exception as exc:  # noqa: BLE001 - price lookup should not block model eval.
            typer.echo(f"Warning: WeyToken price lookup failed: {exc}", err=True)

    targets = [
        CodexCompareTarget(name="official", config_overrides=common_overrides, pricing=official_pricing),
        CodexCompareTarget(name="gateway", config_overrides=gateway_overrides, env=gateway_env, pricing=gateway_pricing),
    ]

    typer.echo(f"Running {len(codex_tasks)} task(s) x 2 target(s) x {repeats} repeat(s)...")
    results, summary = run_codex_compare(
        tasks=codex_tasks,
        targets=targets,
        repeats=repeats,
        out_dir=out,
        codex_bin=codex_bin,
        timeout_seconds=timeout_seconds,
    )
    summary["tasks_path"] = str(tasks)
    summary["gateway_url"] = gateway_url.rstrip("/")
    summary["model_override"] = model
    summary["wire_api"] = wire_api
    summary["pricing_note"] = _pricing_note(model, official_pricing, gateway_pricing)
    summary["gateway_pricing_group"] = gateway_pricing_group
    results_path, summary_path = write_codex_compare_outputs(results, summary, out)
    typer.echo(f"Wrote {results_path}")
    typer.echo(f"Wrote {summary_path}")

    from .codex_report import render_codex_compare_report

    rendered = render_codex_compare_report(out, report_out)
    typer.echo(f"Wrote {rendered}")


@app.command("agent-compare")
def agent_compare_command(
    tasks: Annotated[
        Path,
        typer.Option("--tasks", help="Directory containing task subdirectories."),
    ] = Path("data/codex_tasks"),
    out: Annotated[
        Path,
        typer.Option("--out", help="Output comparison directory."),
    ] = Path("runs/coding-agents"),
    report_out: Annotated[
        Path,
        typer.Option("--report-out", help="Markdown report output path."),
    ] = Path("reports/coding-agents.md"),
    repeats: Annotated[int, typer.Option("--repeats", min=1, help="Repeats per task per agent.")] = 1,
    codex: Annotated[bool, typer.Option("--codex/--no-codex", help="Include Codex CLI as a target.")] = True,
    claude: Annotated[bool, typer.Option("--claude/--no-claude", help="Include Claude Code CLI as a target.")] = True,
    codex_bin: Annotated[str, typer.Option("--codex-bin", help="Codex executable path/name.")] = "codex",
    claude_bin: Annotated[str, typer.Option("--claude-bin", help="Claude Code executable path/name.")] = "claude",
    cctrace: Annotated[bool, typer.Option("--cctrace/--no-cctrace", help="Wrap each agent run with cctrace.")] = False,
    cctrace_bin: Annotated[str, typer.Option("--cctrace-bin", help="cctrace executable path/name.")] = "cctrace",
    codex_model: Annotated[str | None, typer.Option("--codex-model", help="Optional Codex model override.")] = None,
    claude_model: Annotated[str | None, typer.Option("--claude-model", help="Optional Claude Code model override.")] = None,
    claude_gateway_url: Annotated[
        str | None,
        typer.Option("--claude-gateway-url", help="Route Claude Code through an Anthropic-format gateway base URL."),
    ] = None,
    claude_gateway_api_key: Annotated[
        str | None,
        typer.Option("--claude-gateway-api-key", help="Claude gateway API key. It is used only in-process."),
    ] = None,
    claude_gateway_api_key_env: Annotated[
        str,
        typer.Option("--claude-gateway-api-key-env", help="Environment variable containing the Claude gateway API key."),
    ] = "CLAUDE_GATEWAY_API_KEY",
    claude_gateway_auth: Annotated[
        str,
        typer.Option("--claude-gateway-auth", help="Claude gateway auth mode: auth-token or api-key."),
    ] = "auth-token",
    claude_gateway_model_discovery: Annotated[
        bool,
        typer.Option("--claude-gateway-model-discovery/--no-claude-gateway-model-discovery", help="Enable Claude Code /v1/models discovery for the gateway."),
    ] = False,
    codex_profile: Annotated[str | None, typer.Option("--codex-profile", help="Optional Codex config profile.")] = None,
    claude_permission_mode: Annotated[
        str,
        typer.Option("--claude-permission-mode", help="Claude Code permission mode for isolated task workspaces."),
    ] = "bypassPermissions",
    claude_output_format: Annotated[
        str,
        typer.Option("--claude-output-format", help="Claude Code output format used for usage extraction."),
    ] = "stream-json",
    prompt_file: Annotated[str, typer.Option("--prompt-file", help="Task prompt filename.")] = "TASK.md",
    verify_command: Annotated[
        str,
        typer.Option("--verify-command", help="Command to verify a completed task."),
    ] = "bash ./verify.sh",
    timeout_seconds: Annotated[
        int,
        typer.Option("--timeout-seconds", min=1, help="Timeout for each agent and verify command."),
    ] = 1800,
    codex_input_price: Annotated[
        float | None,
        typer.Option("--codex-input-price", help="Optional Codex input price per 1M tokens."),
    ] = None,
    codex_cached_input_price: Annotated[
        float | None,
        typer.Option("--codex-cached-input-price", help="Optional Codex cached-input price per 1M tokens."),
    ] = None,
    codex_output_price: Annotated[
        float | None,
        typer.Option("--codex-output-price", help="Optional Codex output price per 1M tokens."),
    ] = None,
    claude_input_price: Annotated[
        float | None,
        typer.Option("--claude-input-price", help="Optional Claude input price per 1M tokens."),
    ] = None,
    claude_cached_input_price: Annotated[
        float | None,
        typer.Option("--claude-cached-input-price", help="Optional Claude cached-input price per 1M tokens."),
    ] = None,
    claude_output_price: Annotated[
        float | None,
        typer.Option("--claude-output-price", help="Optional Claude output price per 1M tokens."),
    ] = None,
    currency: Annotated[str, typer.Option("--currency", help="Currency for optional cost estimates.")] = "USD",
) -> None:
    """Run the same coding tasks with local Codex and Claude Code subscription CLIs."""
    if not codex and not claude:
        raise typer.BadParameter("At least one target is required. Enable --codex or --claude.")
    if cctrace:
        _require_executable(cctrace_bin, "cctrace")
    if claude_gateway_url and not claude:
        raise typer.BadParameter("--claude-gateway-url requires --claude.")
    if claude_gateway_api_key and not claude_gateway_url:
        raise typer.BadParameter("--claude-gateway-api-key requires --claude-gateway-url.")

    try:
        agent_tasks = discover_agent_tasks(tasks, prompt_file=prompt_file, verify_command=verify_command)
    except AgentCompareError as exc:
        raise typer.BadParameter(str(exc)) from exc

    targets = []
    env_restore: list[tuple[str, str | None]] = []
    if codex:
        _require_executable(codex_bin, "codex")
        codex_pricing = _pricing_from_parts(
            codex_input_price,
            codex_cached_input_price,
            codex_output_price,
            currency,
        )
        targets.append(
            build_codex_agent_target(
                codex_bin=codex_bin,
                model=codex_model,
                profile=codex_profile,
                pricing=codex_pricing,
            )
        )
    if claude:
        _require_executable(claude_bin, "claude")
        claude_env: dict[str, str] = {}
        if claude_gateway_url:
            claude_env = _build_claude_gateway_env(
                gateway_url=claude_gateway_url,
                gateway_api_key=claude_gateway_api_key,
                gateway_api_key_env=claude_gateway_api_key_env,
                auth_mode=claude_gateway_auth,
                model_discovery=claude_gateway_model_discovery,
                env_restore=env_restore,
            )
        claude_pricing = _pricing_from_parts(
            claude_input_price,
            claude_cached_input_price,
            claude_output_price,
            currency,
        )
        targets.append(
            build_claude_agent_target(
                claude_bin=claude_bin,
                model=claude_model,
                permission_mode=claude_permission_mode,
                output_format=claude_output_format,
                pricing=claude_pricing,
                env=claude_env,
            )
        )

    try:
        typer.echo(f"Running {len(agent_tasks)} task(s) x {len(targets)} agent target(s) x {repeats} repeat(s)...")
        results, summary = run_agent_compare(
            tasks=agent_tasks,
            targets=targets,
            repeats=repeats,
            out_dir=out,
            timeout_seconds=timeout_seconds,
            cctrace_enabled=cctrace,
            cctrace_bin=cctrace_bin,
        )
        summary["tasks_path"] = str(tasks)
        summary["note"] = "Targets use local CLI subscriptions/configuration unless gateway options are provided."
        if claude_gateway_url:
            summary["claude_gateway"] = {
                "url": claude_gateway_url.rstrip("/"),
                "auth_mode": claude_gateway_auth,
                "model_discovery": claude_gateway_model_discovery,
                "api_format": "Anthropic Messages",
            }
        results_path, summary_path = write_agent_compare_outputs(results, summary, out)
        typer.echo(f"Wrote {results_path}")
        typer.echo(f"Wrote {summary_path}")

        rendered = render_agent_compare_report(out, report_out)
        typer.echo(f"Wrote {rendered}")
    finally:
        _restore_env_vars(env_restore)


def _require_executable(executable: str, label: str) -> None:
    if Path(executable).exists() or shutil.which(executable):
        return
    raise typer.BadParameter(f"{label} executable not found: {executable}")


def _build_claude_gateway_env(
    gateway_url: str,
    gateway_api_key: str | None,
    gateway_api_key_env: str,
    auth_mode: str,
    model_discovery: bool,
    env_restore: list[tuple[str, str | None]],
) -> dict[str, str]:
    normalized_auth_mode = auth_mode.strip().lower()
    if normalized_auth_mode not in {"auth-token", "api-key"}:
        raise typer.BadParameter("--claude-gateway-auth must be auth-token or api-key.")

    resolved_key_env = _resolve_quick_api_key_env(
        direct_key=gateway_api_key,
        configured_env=gateway_api_key_env,
        temp_env=QUICK_CLAUDE_GATEWAY_API_KEY_ENV,
        label="Claude gateway",
        option_name="--claude-gateway-api-key",
        env_restore=env_restore,
    )
    api_key = os.getenv(resolved_key_env, "")
    env = {"ANTHROPIC_BASE_URL": gateway_url.rstrip("/")}
    if normalized_auth_mode == "auth-token":
        env["ANTHROPIC_AUTH_TOKEN"] = api_key
    else:
        env["ANTHROPIC_API_KEY"] = api_key
    if model_discovery:
        env["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] = "1"
    return env


def _toml_string(value: str) -> str:
    return json.dumps(value)


@app.command("weytoken-pricing")
def weytoken_pricing_command(
    base_url: Annotated[str, typer.Option("--base-url", help="WeyToken base URL.")] = "https://api.weytoken.com",
    group: Annotated[str, typer.Option("--group", help="Pricing group, or best for lowest enabled group.")] = "best",
    official_prices: Annotated[
        Path | None,
        typer.Option("--official-prices", help="Optional CSV/JSON official price catalog."),
    ] = None,
    json_out: Annotated[Path | None, typer.Option("--json-out", help="Write JSON rows.")] = Path("runs/weytoken-pricing.json"),
    csv_out: Annotated[Path | None, typer.Option("--csv-out", help="Write CSV rows.")] = Path("runs/weytoken-pricing.csv"),
    markdown_out: Annotated[
        Path | None,
        typer.Option("--markdown-out", help="Write Markdown price comparison report."),
    ] = Path("reports/weytoken-pricing.md"),
    html_out: Annotated[
        Path | None,
        typer.Option("--html-out", help="Write HTML price comparison report."),
    ] = Path("reports/weytoken-pricing.html"),
    missing_official_out: Annotated[
        Path | None,
        typer.Option("--missing-official-out", help="Write template for models without official prices."),
    ] = Path("runs/weytoken-missing-official.csv"),
    currency: Annotated[str, typer.Option("--currency", help="WeyToken public pricing currency.")] = "CNY",
    usd_cny_rate: Annotated[
        float,
        typer.Option("--usd-cny-rate", help="FX rate for comparing WeyToken CNY prices with official USD prices."),
    ] = DEFAULT_USD_CNY_RATE,
) -> None:
    """Fetch WeyToken model prices and compare them with the official price catalog."""
    try:
        payload = fetch_weytoken_pricing(base_url)
        official = load_official_price_file(official_prices)
        rows = build_weytoken_price_rows(
            payload,
            group=group,
            official_prices=official,
            currency=currency,
            usd_cny_rate=usd_cny_rate,
        )
    except (WeyTokenPricingError, OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    written = write_weytoken_pricing_outputs(
        rows,
        json_out=json_out,
        csv_out=csv_out,
        markdown_out=markdown_out,
        html_out=html_out,
        missing_official_out=missing_official_out,
    )
    matched = sum(1 for row in rows if row.has_official_price)
    typer.echo(f"Fetched {len(rows)} WeyToken model/group price row(s); matched {matched} official price row(s).")
    for path in written:
        typer.echo(f"Wrote {path}")


def _resolve_official_pricing(
    model: str | None,
    input_price: float | None,
    cached_input_price: float | None,
    output_price: float | None,
    currency: str,
) -> TokenPricing | None:
    explicit = _pricing_from_parts(input_price, cached_input_price, output_price, currency)
    if explicit:
        return explicit
    pricing = official_pricing_for_model(model)
    if pricing is None:
        return None
    if pricing.currency == currency:
        return pricing
    return TokenPricing(
        input_per_million=pricing.input_per_million,
        cached_input_per_million=pricing.cached_input_per_million,
        output_per_million=pricing.output_per_million,
        currency=currency,
    )


def _resolve_gateway_pricing(
    official_pricing: TokenPricing | None,
    input_price: float | None,
    cached_input_price: float | None,
    output_price: float | None,
    multiplier: float | None,
    currency: str,
) -> TokenPricing | None:
    explicit = _pricing_from_parts(input_price, cached_input_price, output_price, currency)
    if explicit:
        return explicit
    if multiplier is not None and official_pricing is not None:
        return scaled_pricing(official_pricing, multiplier)
    return None


def _pricing_from_parts(
    input_price: float | None,
    cached_input_price: float | None,
    output_price: float | None,
    currency: str,
) -> TokenPricing | None:
    if input_price is None and output_price is None and cached_input_price is None:
        return None
    if input_price is None or output_price is None:
        raise typer.BadParameter("Pricing requires both input and output prices.")
    return TokenPricing(
        input_per_million=input_price,
        cached_input_per_million=cached_input_price,
        output_per_million=output_price,
        currency=currency,
    )


def _pricing_note(
    model: str | None,
    official_pricing: TokenPricing | None,
    gateway_pricing: TokenPricing | None,
) -> str:
    if official_pricing is None and model:
        return f"No built-in official price for {model}; pass --official-input-price and --official-output-price."
    if official_pricing is not None and gateway_pricing is None:
        return "Official pricing is available, but gateway pricing was not provided; cost delta is unavailable."
    if official_pricing is not None and gateway_pricing is not None:
        return "Cost estimates use Codex JSONL usage multiplied by configured per-1M token prices."
    return "No pricing configured; pass price flags to enable cost comparison."
