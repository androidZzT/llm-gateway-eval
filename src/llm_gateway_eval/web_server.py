from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .audit import audit_config
from .billing import analyze_usage_billing
from .cases import load_cases
from .metrics import aggregate_results
from .models import EvalCase, EvalConfig, Pricing, ProviderTarget, ReportOptions, RunOptions
from .routing import analyze_routing_degradation
from .runner import run_evaluation
from .security import analyze_security_results, build_security_probe_bundle


WEB_GATEWAY_API_KEY_PREFIX = "LLM_GATEWAY_EVAL_WEB_API_KEY_"


@dataclass
class WebEvalJob:
    id: str
    status: str
    created_at: str
    updated_at: str
    config: dict[str, Any]
    out_dir: str
    total_requests: int = 0
    completed_requests: int = 0
    error: str | None = None
    summary: dict[str, Any] | None = None
    audit: dict[str, Any] | None = None
    failures: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "config": self.config,
            "out_dir": self.out_dir,
            "total_requests": self.total_requests,
            "completed_requests": self.completed_requests,
            "error": self.error,
            "summary": self.summary,
            "audit": self.audit,
            "failures": self.failures,
        }


class WebEvalJobStore:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self._jobs: dict[str, WebEvalJob] = {}
        self._lock = threading.Lock()

    def create(self, request: dict[str, Any]) -> WebEvalJob:
        config = _validate_request(request, self.project_root)
        job_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
        out_dir = self.project_root / "runs" / "web-gateway-eval" / f"{_slug(config['model'])}-{job_id}"
        now = _now()
        job = WebEvalJob(
            id=job_id,
            status="queued",
            created_at=now,
            updated_at=now,
            config=_redacted_config(config),
            out_dir=str(out_dir),
        )
        with self._lock:
            self._jobs[job_id] = job
        thread = threading.Thread(
            target=_run_job,
            args=(self, job_id, config, out_dir),
            name=f"llm-gateway-eval-web-{job_id}",
            daemon=True,
        )
        thread.start()
        return job

    def update(self, job_id: str, **updates: Any) -> WebEvalJob:
        with self._lock:
            job = self._jobs[job_id]
            for key, value in updates.items():
                setattr(job, key, value)
            job.updated_at = _now()
            return job

    def get(self, job_id: str) -> WebEvalJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[WebEvalJob]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)


class GatewayEvalHTTPRequestHandler(BaseHTTPRequestHandler):
    server_version = "LLMGatewayEvalWeb/0.1"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API.
        path = urlparse(self.path).path
        if path == "/":
            self._send_html(render_index_html())
            return
        if path == "/api/health":
            self._send_json({"ok": True, "time": _now()})
            return
        if path == "/api/cases":
            self._send_json(_case_catalog(self.server.project_root))  # type: ignore[attr-defined]
            return
        if path == "/api/jobs":
            self._send_json({"jobs": [job.to_dict() for job in self.server.job_store.list()]})  # type: ignore[attr-defined]
            return
        match = re.fullmatch(r"/api/jobs/([^/]+)", path)
        if match:
            job = self.server.job_store.get(match.group(1))  # type: ignore[attr-defined]
            if job is None:
                self._send_json({"error": "job not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(job.to_dict())
            return
        self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API.
        path = urlparse(self.path).path
        if path != "/api/jobs":
            self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
            body = self.rfile.read(length)
            request = json.loads(body.decode("utf-8") or "{}")
            job = self.server.job_store.create(request)  # type: ignore[attr-defined]
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        except json.JSONDecodeError as exc:
            self._send_json({"error": f"invalid JSON: {exc}"}, status=HTTPStatus.BAD_REQUEST)
            return
        self._send_json(job.to_dict(), status=HTTPStatus.ACCEPTED)

    def log_message(self, format: str, *args: Any) -> None:
        message = format % args
        print(f"[web] {self.address_string()} {message}")

    def _send_html(self, text: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = text.encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class GatewayEvalHTTPServer(ThreadingHTTPServer):
    project_root: Path
    job_store: WebEvalJobStore


def serve_gateway_eval_web(host: str, port: int, project_root: str | Path) -> None:
    root = Path(project_root)
    server = GatewayEvalHTTPServer((host, port), GatewayEvalHTTPRequestHandler)
    server.project_root = root
    server.job_store = WebEvalJobStore(root)
    print(f"LLM Gateway Eval web UI running at http://{host}:{port}")
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _run_job(store: WebEvalJobStore, job_id: str, config: dict[str, Any], out_dir: Path) -> None:
    env_name = ""
    previous_env_value: str | None = None
    try:
        store.update(job_id, status="running")
        out_dir.mkdir(parents=True, exist_ok=True)
        env_name, previous_env_value = _prepare_api_key_env(config, job_id)
        eval_cases = _load_selected_cases(store.project_root, config)
        security_probe_bundle = None
        if config["dynamic_security_probes"]:
            security_probe_bundle = build_security_probe_bundle(honeytoken_base_url=config.get("honeytoken_base_url"))
            eval_cases = [*eval_cases, *security_probe_bundle.cases]

        eval_config = _build_eval_config(config, env_name)
        request_count = len(eval_cases) * eval_config.run.repeat_per_case
        store.update(job_id, total_requests=request_count)
        (out_dir / "request.json").write_text(
            json.dumps(_redacted_config(config), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (out_dir / "quick_config.json").write_text(
            json.dumps(_config_to_json(eval_config), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        findings = audit_config(eval_config, online_tls=config["online_tls"])
        audit_payload = {
            "online_tls": config["online_tls"],
            "summary": _summarise_audit_findings(findings),
            "findings": [finding.to_dict() for finding in findings],
        }
        (out_dir / "audit.json").write_text(json.dumps(audit_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if security_probe_bundle is not None:
            (out_dir / "security_probes.json").write_text(
                json.dumps(security_probe_bundle.to_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        results = asyncio.run(run_evaluation(eval_config, eval_cases))
        summary = aggregate_results(eval_config, results)
        summary["config_path"] = str(out_dir / "quick_config.json")
        summary["cases_path"] = config["cases_path"]
        summary["quick_eval"] = {
            "gateway_url": config["gateway_url"],
            "model": config["model"],
            "report_scope": "browser web eval: transport audit, quality probes, privacy/security cases, stability repeats",
            "external_honeytoken_enabled": bool(config.get("honeytoken_base_url")),
        }
        summary["audit"] = audit_payload["summary"]
        summary["audit_path"] = str(out_dir / "audit.json")
        summary["audit_findings"] = audit_payload["findings"]
        summary["security_probes_path"] = str(out_dir / "security_probes.json") if security_probe_bundle else None
        summary["security_analysis"] = analyze_security_results(results, security_probe_bundle)
        summary["usage_billing_analysis"] = analyze_usage_billing(eval_config, eval_cases, results)
        summary["routing_degradation_analysis"] = analyze_routing_degradation(results)
        results_path = out_dir / "results.jsonl"
        summary_path = out_dir / "summary.json"
        results_path.write_text(
            "\n".join(json.dumps(result.to_dict(), ensure_ascii=False) for result in results) + "\n",
            encoding="utf-8",
        )
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        failures = [result.to_dict() for result in results if not result.passed()][:50]
        store.update(
            job_id,
            status="completed",
            completed_requests=len(results),
            summary=summary,
            audit=audit_payload,
            failures=failures,
        )
    except Exception as exc:  # noqa: BLE001 - keep the web job observable.
        store.update(job_id, status="failed", error=f"{exc.__class__.__name__}: {exc}")
    finally:
        if env_name:
            if previous_env_value is None:
                os.environ.pop(env_name, None)
            else:
                os.environ[env_name] = previous_env_value


def _validate_request(request: dict[str, Any], project_root: Path) -> dict[str, Any]:
    gateway_url = str(request.get("gateway_url") or "").strip().rstrip("/")
    model = str(request.get("model") or "").strip()
    api_key = str(request.get("api_key") or "").strip()
    api_key_env = str(request.get("api_key_env") or "").strip()
    if not gateway_url:
        raise ValueError("gateway_url is required.")
    parsed = urlparse(gateway_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("gateway_url must be an http(s) URL.")
    if not model:
        raise ValueError("model is required.")
    if not api_key and not api_key_env:
        raise ValueError("api_key or api_key_env is required.")
    if api_key_env and not os.getenv(api_key_env) and not api_key:
        raise ValueError(f"environment variable is not set: {api_key_env}")

    cases_path = str(request.get("cases_path") or "data/cases/gateway_core.jsonl")
    resolved_cases = (project_root / cases_path).resolve() if not Path(cases_path).is_absolute() else Path(cases_path)
    if not resolved_cases.exists():
        raise ValueError(f"cases file not found: {cases_path}")
    categories = request.get("categories") or ["model_authenticity", "security", "privacy", "stability"]
    if not isinstance(categories, list) or not categories:
        raise ValueError("categories must be a non-empty list.")
    return {
        "gateway_url": gateway_url,
        "model": model,
        "api_key": api_key,
        "api_key_env": api_key_env,
        "cases_path": str(resolved_cases),
        "categories": [str(item) for item in categories],
        "case_limit": _int_range(request.get("case_limit"), 0, 1000, default=12),
        "repeats": _int_range(request.get("repeats"), 1, 20, default=1),
        "attempts": _int_range(request.get("attempts"), 1, 5, default=1),
        "concurrency": _int_range(request.get("concurrency"), 1, 20, default=2),
        "timeout_seconds": _float_range(request.get("timeout_seconds"), 1, 600, default=60),
        "temperature": _float_range(request.get("temperature"), 0, 2, default=0),
        "max_tokens": _int_range(request.get("max_tokens"), 1, 32000, default=1024),
        "stream": bool(request.get("stream")),
        "online_tls": bool(request.get("online_tls", True)),
        "dynamic_security_probes": bool(request.get("dynamic_security_probes", True)),
        "honeytoken_base_url": str(request.get("honeytoken_base_url") or "").strip() or None,
    }


def _prepare_api_key_env(config: dict[str, Any], job_id: str) -> tuple[str, str | None]:
    if config.get("api_key"):
        env_name = WEB_GATEWAY_API_KEY_PREFIX + job_id.replace("-", "_").upper()
        previous = os.environ.get(env_name)
        os.environ[env_name] = config["api_key"]
        return env_name, previous
    return str(config["api_key_env"]), os.environ.get(str(config["api_key_env"]))


def _load_selected_cases(project_root: Path, config: dict[str, Any]) -> list[EvalCase]:
    path = Path(config["cases_path"])
    if not path.is_absolute():
        path = project_root / path
    cases = [case for case in load_cases(path) if case.category in set(config["categories"])]
    limit = int(config.get("case_limit") or 0)
    if limit > 0:
        cases = cases[:limit]
    if not cases:
        raise ValueError("no cases selected.")
    return cases


def _build_eval_config(config: dict[str, Any], api_key_env: str) -> EvalConfig:
    return EvalConfig(
        run=RunOptions(
            timeout_seconds=config["timeout_seconds"],
            concurrency=config["concurrency"],
            attempts=config["attempts"],
            repeat_per_case=config["repeats"],
            stream=config["stream"],
            performance_targets={"p95_latency_seconds": 8},
        ),
        targets=[
            ProviderTarget(
                name="gateway",
                base_url=config["gateway_url"],
                api_key_env=api_key_env,
                model=config["model"],
                params={
                    "temperature": config["temperature"],
                    "max_tokens": config["max_tokens"],
                },
                pricing=Pricing(currency="CNY"),
            )
        ],
        report=ReportOptions(title=f"Web Gateway Evaluation: {config['model']}"),
    )


def _config_to_json(config: EvalConfig) -> dict[str, Any]:
    return {
        "run": config.run.__dict__,
        "targets": [
            {
                **target.__dict__,
                "pricing": target.pricing.__dict__,
            }
            for target in config.targets
        ],
        "report": {
            "title": config.report.title,
            "weights": config.report.weights.__dict__,
        },
    }


def _redacted_config(config: dict[str, Any]) -> dict[str, Any]:
    copied = dict(config)
    if copied.get("api_key"):
        copied["api_key"] = "[redacted]"
    return copied


def _summarise_audit_findings(findings: Any) -> dict[str, int]:
    summary = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for finding in findings:
        if finding.status in summary:
            summary[finding.status] += 1
    summary["total"] = len(findings)
    return summary


def _case_catalog(project_root: Path) -> dict[str, Any]:
    path = project_root / "data" / "cases" / "gateway_core.jsonl"
    cases = load_cases(path)
    counts: dict[str, int] = {}
    for case in cases:
        counts[case.category] = counts.get(case.category, 0) + 1
    return {
        "default_cases_path": str(path),
        "total": len(cases),
        "categories": counts,
    }


def _int_range(value: Any, minimum: int, maximum: int, *, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _float_range(value: Any, minimum: float, maximum: float, *, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-")
    return slug or "gateway"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def render_index_html() -> str:
    return INDEX_HTML


INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LLM Gateway API 测评站</title>
  <style>
    :root {
      --ink: #172026;
      --muted: #60717b;
      --page: #f4f7f6;
      --panel: #ffffff;
      --line: #d7e1df;
      --teal: #08746b;
      --green: #147d3f;
      --red: #b3261e;
      --amber: #9a5c00;
      --blue: #27618a;
      --violet: #635bff;
      --shadow: 0 18px 42px rgba(23, 32, 38, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      background: var(--page);
      font: 14px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    }
    .wrap { width: min(1420px, calc(100% - 36px)); margin: 0 auto; }
    header {
      position: sticky;
      top: 0;
      z-index: 10;
      background: rgba(255, 255, 255, 0.94);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(16px);
    }
    .topbar { display: grid; grid-template-columns: minmax(260px, 1fr) auto; gap: 16px; align-items: center; padding: 18px 0; }
    h1 { margin: 0; font-size: 23px; line-height: 1.2; letter-spacing: 0; }
    .subtitle { margin: 5px 0 0; color: var(--muted); }
    .pills { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
    .pill { border: 1px solid var(--line); border-radius: 999px; padding: 6px 10px; color: var(--muted); background: #fbfdfc; font-size: 12px; }
    main { padding: 20px 0 48px; }
    .layout { display: grid; grid-template-columns: minmax(340px, 420px) minmax(0, 1fr); gap: 16px; align-items: start; }
    .panel, .card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .panel { padding: 18px; }
    .panel + .panel { margin-top: 14px; }
    .panel-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
    h2, h3 { margin: 0; letter-spacing: 0; }
    h2 { font-size: 19px; }
    h3 { font-size: 15px; }
    .muted { color: var(--muted); }
    form { display: grid; gap: 13px; }
    label { display: grid; gap: 6px; color: var(--muted); font-size: 12px; font-weight: 800; }
    input, select {
      width: 100%;
      min-height: 40px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      color: var(--ink);
      font: inherit;
      padding: 8px 10px;
    }
    input[type="checkbox"] { width: 18px; min-height: 18px; }
    .inline { display: flex; align-items: center; gap: 9px; color: var(--ink); font-size: 13px; font-weight: 700; }
    .row { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
    .category-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .toggle {
      display: flex;
      align-items: center;
      gap: 8px;
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 7px 9px;
      background: #fbfdfc;
      font-weight: 700;
      font-size: 13px;
    }
    button {
      border: 0;
      border-radius: 8px;
      background: var(--teal);
      color: #fff;
      cursor: pointer;
      font: inherit;
      font-weight: 800;
      min-height: 42px;
      padding: 9px 13px;
    }
    button.secondary { background: #e8f0ee; color: var(--ink); }
    button:disabled { opacity: 0.55; cursor: not-allowed; }
    .grid { display: grid; gap: 14px; }
    .cards { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .card { min-height: 108px; padding: 15px; box-shadow: none; }
    .card .label { color: var(--muted); font-size: 12px; font-weight: 800; }
    .card strong { display: block; margin-top: 9px; font-size: 27px; line-height: 1.1; letter-spacing: 0; }
    .card .detail { display: block; margin-top: 8px; color: var(--muted); font-size: 12px; }
    .good { color: var(--green); }
    .bad { color: var(--red); }
    .warn { color: var(--amber); }
    .blue { color: var(--blue); }
    .progress { height: 10px; border-radius: 999px; background: #e4ecea; overflow: hidden; }
    .progress > div { width: 0%; height: 100%; border-radius: 999px; background: var(--teal); transition: width 0.2s ease; }
    .tabs { display: flex; gap: 4px; padding: 4px; border: 1px solid var(--line); border-radius: 8px; background: #f8fbfa; overflow: auto; }
    .tab {
      appearance: none;
      border: 0;
      border-radius: 6px;
      background: transparent;
      color: var(--muted);
      min-height: 36px;
      padding: 7px 10px;
      white-space: nowrap;
    }
    .tab.active { color: var(--ink); background: #fff; box-shadow: 0 2px 8px rgba(23, 32, 38, 0.08); }
    .view { display: none; }
    .view.active { display: block; }
    .table-wrap { overflow: auto; border: 1px solid var(--line); border-radius: 8px; background: #fff; }
    table { width: 100%; border-collapse: collapse; min-width: 720px; }
    th, td { padding: 10px 11px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
    th { color: var(--muted); font-size: 12px; background: #f8fbfa; }
    tr:last-child td { border-bottom: 0; }
    .num { text-align: right; font-variant-numeric: tabular-nums; }
    .status { display: inline-flex; border-radius: 999px; padding: 3px 8px; border: 1px solid var(--line); font-size: 12px; font-weight: 800; }
    .status.pass { color: var(--green); background: #edf8f1; border-color: #bfe3cc; }
    .status.fail { color: var(--red); background: #fff0ee; border-color: #f1c2bd; }
    .status.run { color: var(--blue); background: #edf5fb; border-color: #c7ddeb; }
    .split { display: grid; grid-template-columns: minmax(0, 1fr) minmax(320px, 0.8fr); gap: 14px; }
    canvas { display: block; width: 100%; height: 260px; border: 1px solid var(--line); border-radius: 8px; background: #fbfdfc; }
    .empty { padding: 36px; text-align: center; color: var(--muted); }
    .callout { border-left: 4px solid var(--teal); background: #f8fbfa; padding: 12px 13px; border-radius: 8px; color: var(--muted); }
    code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; background: #eef3f2; padding: 2px 4px; border-radius: 4px; }
    @media (max-width: 1100px) {
      .layout, .split { grid-template-columns: 1fr; }
      .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .topbar { grid-template-columns: 1fr; }
      .pills { justify-content: flex-start; }
    }
    @media (max-width: 640px) {
      .wrap { width: min(100% - 24px, 1420px); }
      .cards, .row, .category-grid { grid-template-columns: 1fr; }
      canvas { height: 220px; }
    }
  </style>
</head>
<body>
  <header>
    <div class="wrap topbar">
      <div>
        <h1>LLM Gateway API 测评站</h1>
        <p class="subtitle">本地运行 · OpenAI-compatible Chat Completions</p>
      </div>
      <div class="pills">
        <span class="pill" id="healthPill">服务检查中</span>
        <span class="pill" id="jobPill">未开始</span>
      </div>
    </div>
  </header>
  <main class="wrap">
    <div class="layout">
      <aside>
        <section class="panel">
          <div class="panel-head"><h2>测试配置</h2><span class="muted" id="caseMeta"></span></div>
          <form id="evalForm">
            <label>API Base URL
              <input name="gateway_url" id="gatewayUrl" required placeholder="https://api.example.com/v1" autocomplete="off">
            </label>
            <div class="row">
              <label>Model
                <input name="model" id="model" required placeholder="gpt-4.1-mini" autocomplete="off">
              </label>
              <label>API Key Env
                <input name="api_key_env" id="apiKeyEnv" placeholder="GATEWAY_API_KEY" autocomplete="off">
              </label>
            </div>
            <label>API Key
              <input name="api_key" id="apiKey" type="password" placeholder="sk-..." autocomplete="off">
            </label>
            <div class="category-grid" id="categoryGrid"></div>
            <div class="row">
              <label>Repeats
                <input name="repeats" id="repeats" type="number" min="1" max="20" value="1">
              </label>
              <label>Case Limit
                <input name="case_limit" id="caseLimit" type="number" min="0" max="1000" value="12">
              </label>
            </div>
            <div class="row">
              <label>Concurrency
                <input name="concurrency" id="concurrency" type="number" min="1" max="20" value="2">
              </label>
              <label>Timeout
                <input name="timeout_seconds" id="timeoutSeconds" type="number" min="1" max="600" value="60">
              </label>
            </div>
            <div class="row">
              <label>Max Tokens
                <input name="max_tokens" id="maxTokens" type="number" min="1" max="32000" value="1024">
              </label>
              <label>Temperature
                <input name="temperature" id="temperature" type="number" min="0" max="2" step="0.1" value="0">
              </label>
            </div>
            <label class="inline"><input type="checkbox" id="onlineTls" checked> TLS 在线审计</label>
            <label class="inline"><input type="checkbox" id="dynamicSecurity" checked> 动态 canary / tamper 探针</label>
            <label class="inline"><input type="checkbox" id="stream"> Streaming</label>
            <button id="startButton" type="submit">开始测评</button>
            <button class="secondary" id="loadDemoButton" type="button">填入 WeyToken 示例</button>
          </form>
        </section>
        <section class="panel">
          <div class="panel-head"><h2>运行状态</h2><span id="statusBadge" class="status">IDLE</span></div>
          <div class="progress"><div id="progressBar"></div></div>
          <p class="muted" id="statusText">等待配置</p>
          <p class="muted" id="outDir"></p>
        </section>
      </aside>

      <section>
        <div class="grid cards" id="cards"></div>
        <section class="panel">
          <div class="panel-head">
            <div class="tabs">
              <button class="tab active" data-view="overview" type="button">总览</button>
              <button class="tab" data-view="quality" type="button">质量</button>
              <button class="tab" data-view="security" type="button">安全</button>
              <button class="tab" data-view="errors" type="button">错误</button>
              <button class="tab" data-view="artifacts" type="button">产物</button>
            </div>
            <span class="muted" id="generatedAt"></span>
          </div>
          <div id="overview" class="view active">
            <div class="split">
              <canvas id="categoryChart" width="760" height="300"></canvas>
              <div class="callout" id="verdict">尚未运行测评。</div>
            </div>
          </div>
          <div id="quality" class="view">
            <div class="table-wrap"><table id="categoryTable"></table></div>
          </div>
          <div id="security" class="view">
            <div class="table-wrap"><table id="auditTable"></table></div>
          </div>
          <div id="errors" class="view">
            <div class="split">
              <canvas id="errorChart" width="760" height="300"></canvas>
              <div class="table-wrap"><table id="failureTable"></table></div>
            </div>
          </div>
          <div id="artifacts" class="view">
            <div class="table-wrap"><table id="artifactTable"></table></div>
          </div>
        </section>
      </section>
    </div>
  </main>
  <script>
    const state = { job: null, pollTimer: null, view: "overview" };
    const $ = (id) => document.getElementById(id);
    const esc = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const fmtPct = (value) => {
      if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
      let n = Number(value);
      if (Math.abs(n) <= 1) n *= 100;
      return `${n.toFixed(1)}%`;
    };
    const fmtInt = (value) => value === null || value === undefined ? "n/a" : Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 0 });
    const tone = (value, good = 0.95, warn = 0.7) => value >= good ? "good" : value >= warn ? "warn" : "bad";
    const statusHtml = (status) => {
      const cls = status === "PASS" || status === "completed" ? "pass" : status === "running" || status === "queued" ? "run" : "fail";
      return `<span class="status ${cls}">${esc(status || "-")}</span>`;
    };
    function table(headers, rows, empty = "暂无数据") {
      return `<thead><tr>${headers.map(h => `<th class="${h.cls || ""}">${esc(h.label)}</th>`).join("")}</tr></thead><tbody>${rows.length ? rows.join("") : `<tr><td colspan="${headers.length}"><div class="empty">${empty}</div></td></tr>`}</tbody>`;
    }
    async function api(path, options = {}) {
      const response = await fetch(path, { ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || response.statusText);
      return payload;
    }
    async function init() {
      try {
        const health = await api("/api/health");
        $("healthPill").textContent = health.ok ? "服务可用" : "服务异常";
        const cases = await api("/api/cases");
        $("caseMeta").textContent = `${fmtInt(cases.total)} cases`;
        const categories = cases.categories || {};
        $("categoryGrid").innerHTML = Object.entries(categories).map(([name, count]) => `
          <label class="toggle"><input type="checkbox" name="category" value="${esc(name)}" checked>${esc(name)} <span class="muted">${fmtInt(count)}</span></label>
        `).join("");
      } catch (error) {
        $("healthPill").textContent = "服务异常";
        $("statusText").textContent = error.message;
      }
      renderEmpty();
    }
    function requestFromForm() {
      const categories = [...document.querySelectorAll("input[name=category]:checked")].map(input => input.value);
      return {
        gateway_url: $("gatewayUrl").value.trim(),
        model: $("model").value.trim(),
        api_key: $("apiKey").value.trim(),
        api_key_env: $("apiKeyEnv").value.trim(),
        categories,
        repeats: Number($("repeats").value || 1),
        case_limit: Number($("caseLimit").value || 0),
        concurrency: Number($("concurrency").value || 2),
        timeout_seconds: Number($("timeoutSeconds").value || 60),
        max_tokens: Number($("maxTokens").value || 1024),
        temperature: Number($("temperature").value || 0),
        online_tls: $("onlineTls").checked,
        dynamic_security_probes: $("dynamicSecurity").checked,
        stream: $("stream").checked,
      };
    }
    async function startJob(event) {
      event.preventDefault();
      $("startButton").disabled = true;
      $("statusText").textContent = "提交中";
      try {
        const job = await api("/api/jobs", { method: "POST", body: JSON.stringify(requestFromForm()) });
        state.job = job;
        $("apiKey").value = "";
        renderJob(job);
        beginPolling(job.id);
      } catch (error) {
        $("statusText").textContent = error.message;
        $("startButton").disabled = false;
      }
    }
    function beginPolling(jobId) {
      clearInterval(state.pollTimer);
      state.pollTimer = setInterval(async () => {
        try {
          const job = await api(`/api/jobs/${jobId}`);
          state.job = job;
          renderJob(job);
          if (["completed", "failed"].includes(job.status)) {
            clearInterval(state.pollTimer);
            $("startButton").disabled = false;
          }
        } catch (error) {
          $("statusText").textContent = error.message;
        }
      }, 1500);
    }
    function renderEmpty() {
      $("cards").innerHTML = [
        ["请求成功率", "n/a", "等待运行", "blue"],
        ["用例通过率", "n/a", "等待运行", "blue"],
        ["安全探针", "n/a", "等待运行", "blue"],
        ["错误数", "n/a", "等待运行", "blue"],
      ].map(card).join("");
      $("categoryTable").innerHTML = table([{ label: "分类" }, { label: "请求成功率", cls: "num" }, { label: "用例通过率", cls: "num" }, { label: "错误", cls: "num" }], []);
      $("auditTable").innerHTML = table([{ label: "检查项" }, { label: "状态" }, { label: "证据" }, { label: "说明" }], []);
      $("failureTable").innerHTML = table([{ label: "Case" }, { label: "分类" }, { label: "错误类型" }, { label: "错误" }], []);
      $("artifactTable").innerHTML = table([{ label: "文件" }, { label: "路径" }], []);
      drawBars("categoryChart", [], []);
      drawBars("errorChart", [], []);
    }
    function card([label, value, detail, cls]) {
      return `<article class="card"><span class="label">${esc(label)}</span><strong class="${cls || ""}">${esc(value)}</strong><span class="detail">${esc(detail)}</span></article>`;
    }
    function renderJob(job) {
      $("jobPill").textContent = `${job.status} ${job.id}`;
      $("statusBadge").outerHTML = statusHtml(job.status).replace("<span", '<span id="statusBadge"');
      const progress = job.total_requests ? Math.min(100, (job.completed_requests / job.total_requests) * 100) : (job.status === "running" ? 20 : 0);
      $("progressBar").style.width = `${progress}%`;
      $("statusText").textContent = job.error || `${fmtInt(job.completed_requests)}/${fmtInt(job.total_requests)} requests`;
      $("outDir").innerHTML = job.out_dir ? `<code>${esc(job.out_dir)}</code>` : "";
      if (job.summary) renderSummary(job);
      if (job.status === "failed") $("verdict").textContent = job.error || "运行失败";
    }
    function renderSummary(job) {
      const summary = job.summary || {};
      const provider = ((summary.providers || {}).gateway) || {};
      const analysis = summary.security_analysis || {};
      const audit = job.audit || {};
      const auditSummary = audit.summary || {};
      $("generatedAt").textContent = summary.generated_at || job.updated_at || "";
      $("cards").innerHTML = [
        ["请求成功率", fmtPct(provider.request_success_rate), `${fmtInt(provider.request_success_count)}/${fmtInt(provider.total)}`, tone(provider.request_success_rate || 0)],
        ["用例通过率", fmtPct(provider.case_pass_rate), `${fmtInt(provider.case_pass_count)}/${fmtInt(provider.total)}`, tone(provider.case_pass_rate || 0)],
        ["安全探针", fmtPct(analysis.generated_probe_pass_rate), `${fmtInt(analysis.canary_leakage_event_count || 0)} canary leak`, tone(analysis.generated_probe_pass_rate || 0, 0.95, 0.8)],
        ["错误数", fmtInt(provider.error_count), Object.entries(provider.error_types || {}).map(([k, v]) => `${k}: ${v}`).join(" / ") || "-", provider.error_count ? "bad" : "good"],
      ].map(card).join("");
      const categories = summary.categories || {};
      const categoryRows = Object.entries(categories).map(([name, row]) => `
        <tr><td><strong>${esc(name)}</strong></td><td class="num">${fmtPct(row.request_success_rate)}</td><td class="num">${fmtPct(row.case_pass_rate)}</td><td class="num">${fmtInt(row.error_count)}</td></tr>
      `);
      $("categoryTable").innerHTML = table([{ label: "分类" }, { label: "请求成功率", cls: "num" }, { label: "用例通过率", cls: "num" }, { label: "错误", cls: "num" }], categoryRows);
      const findings = audit.findings || summary.audit_findings || [];
      $("auditTable").innerHTML = table([{ label: "检查项" }, { label: "状态" }, { label: "证据" }, { label: "说明" }], findings.map(row => `
        <tr><td>${esc(row.check)}</td><td>${statusHtml(row.status)}</td><td><code>${esc(row.evidence || "-")}</code></td><td>${esc(row.message || "-")}</td></tr>
      `));
      const failures = job.failures || [];
      $("failureTable").innerHTML = table([{ label: "Case" }, { label: "分类" }, { label: "错误类型" }, { label: "错误" }], failures.map(row => `
        <tr><td>${esc(row.case_id)}</td><td>${esc(row.category)}</td><td>${esc(row.error_type || "-")}</td><td>${esc(row.error || "-")}</td></tr>
      `));
      $("artifactTable").innerHTML = table([{ label: "文件" }, { label: "路径" }], ["request.json", "quick_config.json", "audit.json", "security_probes.json", "results.jsonl", "summary.json"].map(file => `
        <tr><td>${esc(file)}</td><td><code>${esc(job.out_dir + "/" + file)}</code></td></tr>
      `));
      $("verdict").innerHTML = verdict(provider, auditSummary, analysis);
      drawBars("categoryChart", Object.keys(categories), Object.values(categories).map(row => Math.round((row.case_pass_rate || 0) * 100)));
      drawBars("errorChart", Object.keys(provider.error_types || {}), Object.values(provider.error_types || {}), "#b3261e");
    }
    function verdict(provider, audit, analysis) {
      if ((audit.FAIL || 0) > 0) return "<strong>传输配置不合格。</strong>优先修复 HTTPS/TLS 后再看模型质量。";
      if ((provider.request_success_rate || 0) < 0.95) return "<strong>API 稳定性偏低。</strong>当前错误率较高，应先排查接口兼容、认证、限流或模型路由。";
      if ((analysis.canary_leakage_event_count || 0) > 0) return "<strong>发现隐私 canary 泄漏。</strong>需要逐条检查输出和日志链路。";
      return "<strong>当前样本未发现硬伤。</strong>建议扩大样本并加入官方基线复测。";
    }
    function drawBars(id, labels, values, color = "#08746b") {
      const canvas = $(id);
      const rect = canvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.floor(rect.width * ratio));
      canvas.height = Math.max(1, Math.floor(rect.height * ratio));
      const ctx = canvas.getContext("2d");
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      ctx.clearRect(0, 0, rect.width, rect.height);
      if (!labels.length) {
        ctx.fillStyle = "#60717b";
        ctx.font = "14px system-ui, sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("暂无图表数据", rect.width / 2, rect.height / 2);
        return;
      }
      const pad = { left: 44, right: 16, top: 26, bottom: 58 };
      const max = Math.max(1, ...values);
      const plotW = rect.width - pad.left - pad.right;
      const plotH = rect.height - pad.top - pad.bottom;
      ctx.strokeStyle = "#d7e1df";
      ctx.beginPath();
      for (let i = 0; i <= 4; i += 1) {
        const y = pad.top + (plotH * i) / 4;
        ctx.moveTo(pad.left, y);
        ctx.lineTo(rect.width - pad.right, y);
        ctx.fillStyle = "#60717b";
        ctx.font = "11px system-ui, sans-serif";
        ctx.textAlign = "right";
        ctx.fillText(fmtInt(max * (1 - i / 4)), pad.left - 8, y + 4);
      }
      ctx.stroke();
      const slot = plotW / labels.length;
      const barW = Math.min(58, slot - 16);
      labels.forEach((label, index) => {
        const value = Number(values[index] || 0);
        const h = (value / max) * plotH;
        const x = pad.left + index * slot + (slot - barW) / 2;
        const y = pad.top + plotH - h;
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.roundRect(x, y, barW, h, 5);
        ctx.fill();
        ctx.fillStyle = "#172026";
        ctx.font = "12px system-ui, sans-serif";
        ctx.textAlign = "center";
        ctx.fillText(fmtInt(value), x + barW / 2, y - 6);
        ctx.fillStyle = "#60717b";
        ctx.fillText(String(label).slice(0, 16), x + barW / 2, rect.height - 24);
      });
    }
    function bind() {
      $("evalForm").addEventListener("submit", startJob);
      $("loadDemoButton").addEventListener("click", () => {
        $("gatewayUrl").value = "https://api.weytoken.com/v1";
        $("model").value = "gpt-5.5";
        $("apiKeyEnv").value = "GATEWAY_API_KEY";
      });
      document.querySelectorAll(".tab").forEach(button => button.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach(item => item.classList.toggle("active", item === button));
        document.querySelectorAll(".view").forEach(view => view.classList.toggle("active", view.id === button.dataset.view));
        requestAnimationFrame(() => {
          if (state.job?.summary) renderSummary(state.job);
        });
      }));
      window.addEventListener("resize", () => {
        if (state.job?.summary) renderSummary(state.job);
        else renderEmpty();
      });
    }
    bind();
    init();
  </script>
</body>
</html>
"""
