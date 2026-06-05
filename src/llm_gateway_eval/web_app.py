from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def render_eval_web_app(
    *,
    coding_run: str | Path,
    security_run: str | Path,
    output_path: str | Path,
    benchmark_run: str | Path | None = None,
    gateway_url: str = "",
    model: str = "",
    title: str = "LLM Gateway 真实评测工作台",
) -> Path:
    coding_path = Path(coding_run)
    security_path = Path(security_run)
    benchmark_path = Path(benchmark_run) if benchmark_run else None
    payload = build_web_app_payload(
        coding_run=coding_path,
        security_run=security_path,
        benchmark_run=benchmark_path,
        gateway_url=gateway_url,
        model=model,
        title=title,
    )
    rendered = HTML_TEMPLATE.replace("__TITLE__", _html_escape(title)).replace(
        "__APP_DATA__",
        json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"),
    )
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered, encoding="utf-8")
    return out


def build_web_app_payload(
    *,
    coding_run: Path,
    security_run: Path,
    benchmark_run: Path | None,
    gateway_url: str,
    model: str,
    title: str,
) -> dict[str, Any]:
    coding_summary = _load_json(coding_run / "summary.json")
    coding_rows = _load_jsonl(coding_run / "results.jsonl")
    security_summary = _load_json(security_run / "summary.json")
    security_rows = _load_jsonl(security_run / "results.jsonl")
    audit = _load_json(security_run / "audit.json")
    benchmark = _load_benchmark(benchmark_run)

    targets = coding_summary.get("targets_summary") or {}
    official = targets.get("official") or {}
    gateway = targets.get("gateway") or {}
    provider = (security_summary.get("providers") or {}).get("gateway") or {}
    security_analysis = security_summary.get("security_analysis") or {}
    quick_eval = security_summary.get("quick_eval") or {}
    resolved_gateway_url = gateway_url or coding_summary.get("gateway_url") or quick_eval.get("gateway_url") or ""
    resolved_model = model or coding_summary.get("model_override") or quick_eval.get("model") or ""

    return {
        "meta": {
            "title": title,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "coding_run": str(coding_run),
            "security_run": str(security_run),
            "benchmark_run": str(benchmark_run) if benchmark_run else "",
            "gateway_url": resolved_gateway_url,
            "model": resolved_model,
            "task_count": coding_summary.get("task_count") or len({row.get("task_id") for row in coding_rows}),
            "coding_runs": coding_summary.get("total_runs") or len(coding_rows),
            "security_requests": provider.get("total") or len(security_rows),
        },
        "cards": _cards(official, gateway, provider, audit, coding_rows, security_analysis),
        "coding": {
            "targets": targets,
            "task_rows": _task_rows(coding_summary, coding_rows),
            "run_rows": _coding_run_rows(coding_rows),
            "duration_chart": _duration_chart_rows(coding_rows),
            "token_breakdown": _token_breakdown(targets),
        },
        "security": {
            "provider": provider,
            "categories": security_summary.get("categories") or {},
            "analysis": security_analysis,
            "audit_summary": audit.get("summary") or {},
            "audit_findings": audit.get("findings") or security_summary.get("audit_findings") or [],
            "failure_rows": _security_failure_rows(security_rows),
            "error_chart": _error_chart(provider),
        },
        "benchmark": benchmark,
    }


def _cards(
    official: dict[str, Any],
    gateway: dict[str, Any],
    provider: dict[str, Any],
    audit: dict[str, Any],
    coding_rows: list[dict[str, Any]],
    security_analysis: dict[str, Any],
) -> list[dict[str, Any]]:
    official_pass = _ratio_text(official.get("passed"), official.get("runs"))
    gateway_pass = _ratio_text(gateway.get("passed"), gateway.get("runs"))
    token_delta = _delta_percent(
        (gateway.get("usage") or {}).get("total_tokens"),
        (official.get("usage") or {}).get("total_tokens"),
    )
    duration_delta = _delta_percent(
        gateway.get("avg_codex_duration_seconds"),
        official.get("avg_codex_duration_seconds"),
    )
    p95 = _p95_by_target(coding_rows)
    p95_delta = _delta_percent(p95.get("gateway"), p95.get("official"))
    audit_summary = audit.get("summary") or {}
    return [
        {
            "label": "任务完成质量",
            "value": f"{gateway_pass} / {official_pass}",
            "detail": "中转 / 官方",
            "tone": "good" if gateway.get("pass_rate") == official.get("pass_rate") else "warn",
        },
        {
            "label": "中转 API 成功率",
            "value": _format_percent(provider.get("request_success_rate")),
            "detail": _ratio_text(provider.get("request_success_count"), provider.get("total")),
            "tone": "good" if _as_float(provider.get("request_success_rate"), 0) >= 0.95 else "bad",
        },
        {
            "label": "传输审计",
            "value": f"{audit_summary.get('FAIL', 0)} FAIL",
            "detail": f"{audit_summary.get('PASS', 0)} PASS / {audit_summary.get('WARN', 0)} WARN",
            "tone": "good" if int(audit_summary.get("FAIL") or 0) == 0 else "bad",
        },
        {
            "label": "Token 差异",
            "value": _format_delta(token_delta),
            "detail": "中转 total tokens vs 官方",
            "tone": "good" if token_delta is not None and token_delta <= 0 else "warn",
        },
        {
            "label": "平均耗时差异",
            "value": _format_delta(duration_delta),
            "detail": "中转 Codex 端到端耗时",
            "tone": "good" if duration_delta is not None and duration_delta <= 5 else "warn",
        },
        {
            "label": "P95 耗时差异",
            "value": _format_delta(p95_delta),
            "detail": "长尾体验",
            "tone": "good" if p95_delta is not None and p95_delta <= 5 else "bad",
        },
        {
            "label": "Canary 泄漏",
            "value": str(security_analysis.get("canary_leakage_event_count") or 0),
            "detail": "输出侧隐私探针",
            "tone": "good" if int(security_analysis.get("canary_leakage_event_count") or 0) == 0 else "bad",
        },
    ]


def _task_rows(summary: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tasks = sorted({row.get("task_id") for row in rows if row.get("task_id")})
    paired = {item.get("task_id"): item for item in summary.get("paired_task_deltas") or []}
    output = []
    for task_id in tasks:
        official_rows = [row for row in rows if row.get("task_id") == task_id and row.get("target") == "official"]
        gateway_rows = [row for row in rows if row.get("task_id") == task_id and row.get("target") == "gateway"]
        item = paired.get(task_id, {})
        rates = item.get("target_pass_rates") or {}
        output.append(
            {
                "task_id": task_id,
                "official_pass_rate": rates.get("official", _pass_rate(official_rows)),
                "gateway_pass_rate": rates.get("gateway", _pass_rate(gateway_rows)),
                "delta": item.get("max_delta", _max_rate_delta(official_rows, gateway_rows)),
                "official_avg_duration": _avg(row.get("codex_duration_seconds") for row in official_rows),
                "gateway_avg_duration": _avg(row.get("codex_duration_seconds") for row in gateway_rows),
                "official_avg_tokens": _avg((row.get("usage") or {}).get("total_tokens") for row in official_rows),
                "gateway_avg_tokens": _avg((row.get("usage") or {}).get("total_tokens") for row in gateway_rows),
                "runs": len(official_rows) + len(gateway_rows),
            }
        )
    return output


def _coding_run_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "task_id": row.get("task_id"),
            "target": row.get("target"),
            "repeat_index": row.get("repeat_index"),
            "passed": bool(row.get("passed")),
            "duration": row.get("codex_duration_seconds"),
            "verify_duration": row.get("verify_duration_seconds"),
            "total_tokens": (row.get("usage") or {}).get("total_tokens"),
            "reasoning_tokens": (row.get("usage") or {}).get("reasoning_output_tokens"),
            "changed_files": row.get("changed_files") or [],
            "error": row.get("error"),
        }
        for row in rows
    ]


def _duration_chart_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tasks = sorted({row.get("task_id") for row in rows if row.get("task_id")})
    return [
        {
            "task_id": task_id,
            "official": _avg(
                row.get("codex_duration_seconds")
                for row in rows
                if row.get("task_id") == task_id and row.get("target") == "official"
            ),
            "gateway": _avg(
                row.get("codex_duration_seconds")
                for row in rows
                if row.get("task_id") == task_id and row.get("target") == "gateway"
            ),
        }
        for task_id in tasks
    ]


def _token_breakdown(targets: dict[str, Any]) -> list[dict[str, Any]]:
    keys = [
        ("input_tokens", "Input"),
        ("cached_input_tokens", "Cached"),
        ("output_tokens", "Output"),
        ("reasoning_output_tokens", "Reasoning"),
    ]
    rows = []
    for target in ("official", "gateway"):
        usage = (targets.get(target) or {}).get("usage") or {}
        rows.append(
            {
                "target": target,
                "values": [{"key": key, "label": label, "value": usage.get(key) or 0} for key, label in keys],
            }
        )
    return rows


def _security_failure_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        if row.get("passed") and not row.get("error"):
            continue
        output.append(
            {
                "case_id": row.get("case_id"),
                "category": row.get("category"),
                "error_type": row.get("error_type"),
                "attempts": row.get("attempts"),
                "error": row.get("error"),
                "passed": bool(row.get("passed")),
            }
        )
    return output


def _error_chart(provider: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"label": str(error_type), "value": count}
        for error_type, count in sorted((provider.get("error_types") or {}).items())
    ]


def _load_benchmark(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    if path.is_dir():
        for candidate in (path / "summary.json", path / "benchmark-results.json", path / "benchmark-plan.json"):
            if candidate.exists():
                return _load_json(candidate)
        return {}
    if path.exists():
        return _load_json(path)
    return {}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _pass_rate(rows: list[dict[str, Any]]) -> float | None:
    if not rows:
        return None
    return sum(1 for row in rows if row.get("passed")) / len(rows)


def _max_rate_delta(first: list[dict[str, Any]], second: list[dict[str, Any]]) -> float | None:
    rates = [rate for rate in (_pass_rate(first), _pass_rate(second)) if rate is not None]
    if not rates:
        return None
    return max(rates) - min(rates)


def _p95_by_target(rows: list[dict[str, Any]]) -> dict[str, float]:
    output = {}
    for target in sorted({row.get("target") for row in rows if row.get("target")}):
        values = [
            float(row["codex_duration_seconds"])
            for row in rows
            if row.get("target") == target and row.get("codex_duration_seconds") is not None
        ]
        if values:
            output[str(target)] = _percentile(values, 95)
    return output


def _percentile(values: list[float], percent: float) -> float:
    values = sorted(values)
    if not values:
        return 0.0
    index = (len(values) - 1) * percent / 100
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    weight = index - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def _avg(values: Any) -> float | None:
    numbers = []
    for value in values:
        number = _as_float(value)
        if number is not None:
            numbers.append(number)
    if not numbers:
        return None
    return sum(numbers) / len(numbers)


def _delta_percent(new: Any, old: Any) -> float | None:
    new_value = _as_float(new)
    old_value = _as_float(old)
    if new_value is None or old_value in (None, 0):
        return None
    return (new_value - old_value) / old_value * 100


def _as_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _ratio_text(numerator: Any, denominator: Any) -> str:
    if numerator is None or denominator is None:
        return "n/a"
    return f"{int(numerator)}/{int(denominator)}"


def _format_percent(value: Any) -> str:
    number = _as_float(value)
    if number is None:
        return "n/a"
    if abs(number) <= 1:
        number *= 100
    return f"{number:.1f}%"


def _format_delta(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}%"


def _html_escape(value: Any) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


HTML_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>__TITLE__</title>
  <style>
    :root {
      --ink: #172026;
      --muted: #5e6c76;
      --page: #f4f7f6;
      --panel: #ffffff;
      --line: #d7e1df;
      --teal: #08746b;
      --green: #147d3f;
      --red: #b3261e;
      --amber: #9a5c00;
      --violet: #635bff;
      --blue: #27618a;
      --shadow: 0 18px 42px rgba(23, 32, 38, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      background: var(--page);
      font: 14px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    }
    .app-shell { min-height: 100vh; display: grid; grid-template-rows: auto 1fr; }
    header {
      position: sticky;
      top: 0;
      z-index: 10;
      background: rgba(255, 255, 255, 0.92);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(16px);
    }
    .wrap { width: min(1380px, calc(100% - 36px)); margin: 0 auto; }
    .topbar { display: grid; grid-template-columns: minmax(220px, 1fr) auto; gap: 18px; align-items: center; padding: 18px 0 14px; }
    .brand h1 { margin: 0; font-size: 22px; line-height: 1.2; letter-spacing: 0; }
    .brand p { margin: 5px 0 0; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .meta-strip { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
    .pill {
      border: 1px solid var(--line);
      background: #fbfdfc;
      border-radius: 999px;
      padding: 6px 10px;
      color: var(--muted);
      font-size: 12px;
      max-width: 320px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .toolbar { display: grid; grid-template-columns: 1fr auto auto; gap: 12px; align-items: center; padding: 0 0 14px; }
    .tabs, .segmented { display: flex; gap: 4px; padding: 4px; border: 1px solid var(--line); border-radius: 8px; background: #f8fbfa; overflow: auto; }
    .tab, .segment {
      appearance: none;
      border: 0;
      border-radius: 6px;
      background: transparent;
      color: var(--muted);
      cursor: pointer;
      font: inherit;
      font-weight: 700;
      padding: 8px 11px;
      white-space: nowrap;
    }
    .tab.active, .segment.active { color: var(--ink); background: #ffffff; box-shadow: 0 2px 8px rgba(23, 32, 38, 0.08); }
    .search { width: 260px; height: 40px; border: 1px solid var(--line); border-radius: 8px; padding: 0 12px; color: var(--ink); background: #fff; font: inherit; }
    main { padding: 20px 0 44px; }
    .section { display: none; }
    .section.active { display: block; }
    .grid { display: grid; gap: 14px; }
    .grid.cards { grid-template-columns: repeat(7, minmax(0, 1fr)); }
    .grid.two { grid-template-columns: minmax(0, 1.15fr) minmax(360px, 0.85fr); }
    .grid.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .panel, .card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .card { min-height: 116px; padding: 15px; box-shadow: none; }
    .card .label { color: var(--muted); font-size: 12px; font-weight: 700; }
    .card .value { display: block; margin-top: 10px; font-size: 25px; line-height: 1.1; font-weight: 800; letter-spacing: 0; }
    .card .detail { display: block; margin-top: 8px; color: var(--muted); font-size: 12px; }
    .panel { padding: 18px; margin-top: 14px; }
    .panel h2, .panel h3 { margin: 0 0 12px; letter-spacing: 0; }
    .panel h2 { font-size: 20px; }
    .panel h3 { font-size: 16px; }
    .panel-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
    .muted { color: var(--muted); }
    .good { color: var(--green); }
    .bad { color: var(--red); }
    .warn { color: var(--amber); }
    .blue { color: var(--blue); }
    .violet { color: var(--violet); }
    canvas { display: block; width: 100%; height: 280px; border: 1px solid var(--line); border-radius: 8px; background: #fbfdfc; }
    .table-wrap { overflow: auto; border: 1px solid var(--line); border-radius: 8px; background: #fff; }
    table { width: 100%; border-collapse: collapse; min-width: 760px; }
    th, td { padding: 11px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
    th { color: var(--muted); font-size: 12px; background: #f8fbfa; position: sticky; top: 0; z-index: 1; }
    tr:last-child td { border-bottom: 0; }
    .num { text-align: right; font-variant-numeric: tabular-nums; }
    .status {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 68px;
      border-radius: 999px;
      padding: 3px 9px;
      border: 1px solid var(--line);
      font-size: 12px;
      font-weight: 800;
    }
    .status.pass { color: var(--green); background: #edf8f1; border-color: #bfe3cc; }
    .status.fail { color: var(--red); background: #fff0ee; border-color: #f1c2bd; }
    .callout { border-left: 4px solid var(--teal); background: #f8fbfa; padding: 13px 14px; border-radius: 8px; color: var(--muted); }
    .split-list { display: grid; gap: 10px; }
    .list-item { display: grid; grid-template-columns: 160px 1fr auto; gap: 12px; align-items: center; padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: #fbfdfc; }
    .list-item strong { font-size: 14px; }
    .bars { display: grid; gap: 10px; }
    .bar-row { display: grid; grid-template-columns: 110px 1fr 70px; align-items: center; gap: 10px; }
    .bar-track { height: 10px; border-radius: 999px; background: #e7eeec; overflow: hidden; }
    .bar-fill { height: 100%; border-radius: 999px; background: var(--teal); }
    code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; background: #eef3f2; padding: 2px 4px; border-radius: 4px; }
    .empty { padding: 28px; text-align: center; color: var(--muted); }
    @media (max-width: 1080px) {
      .grid.cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .grid.two, .grid.three { grid-template-columns: 1fr; }
      .toolbar { grid-template-columns: 1fr; }
      .search { width: 100%; }
      .meta-strip { justify-content: flex-start; }
      .topbar { grid-template-columns: 1fr; }
    }
    @media (max-width: 640px) {
      .wrap { width: min(100% - 24px, 1380px); }
      .grid.cards { grid-template-columns: 1fr; }
      .brand p { white-space: normal; }
      .card { min-height: 94px; }
      canvas { height: 220px; }
      .list-item { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="app-shell">
    <header>
      <div class="wrap">
        <div class="topbar">
          <div class="brand">
            <h1 id="pageTitle">真实评测工作台</h1>
            <p id="pageSubtitle"></p>
          </div>
          <div class="meta-strip" id="metaStrip"></div>
        </div>
        <div class="toolbar">
          <nav class="tabs" aria-label="评测维度">
            <button class="tab active" data-tab="overview">总览</button>
            <button class="tab" data-tab="quality">任务质量</button>
            <button class="tab" data-tab="security">安全</button>
            <button class="tab" data-tab="tokens">Token</button>
            <button class="tab" data-tab="performance">性能</button>
            <button class="tab" data-tab="benchmark">Benchmark</button>
            <button class="tab" data-tab="details">明细</button>
          </nav>
          <div class="segmented" aria-label="目标筛选">
            <button class="segment active" data-target="all">全部</button>
            <button class="segment" data-target="official">官方</button>
            <button class="segment" data-target="gateway">中转</button>
            <button class="segment" data-target="failed">失败</button>
          </div>
          <input class="search" id="searchBox" type="search" placeholder="搜索任务、错误、文件">
        </div>
      </div>
    </header>

    <main class="wrap">
      <section id="overview" class="section active">
        <div class="grid cards" id="cards"></div>
        <div class="grid two">
          <div class="panel">
            <div class="panel-head"><h2>任务耗时</h2><span class="muted">Codex 端到端秒数</span></div>
            <canvas id="durationChart" width="900" height="320"></canvas>
          </div>
          <div class="panel">
            <div class="panel-head"><h2>安全状态</h2><span class="muted" id="securityBadge"></span></div>
            <div class="split-list" id="securityOverview"></div>
          </div>
        </div>
      </section>

      <section id="quality" class="section">
        <div class="panel">
          <div class="panel-head"><h2>任务完成质量</h2><span class="muted" id="qualityCount"></span></div>
          <div class="table-wrap"><table id="taskTable"></table></div>
        </div>
      </section>

      <section id="security" class="section">
        <div class="grid two">
          <div class="panel">
            <div class="panel-head"><h2>API 错误分布</h2><span class="muted">quick eval</span></div>
            <canvas id="errorChart" width="760" height="300"></canvas>
          </div>
          <div class="panel">
            <div class="panel-head"><h2>TLS 与配置审计</h2><span class="muted" id="auditSummary"></span></div>
            <div class="table-wrap"><table id="auditTable"></table></div>
          </div>
        </div>
        <div class="panel">
          <div class="panel-head"><h2>失败用例</h2><span class="muted" id="failureCount"></span></div>
          <div class="table-wrap"><table id="securityFailureTable"></table></div>
        </div>
      </section>

      <section id="tokens" class="section">
        <div class="grid two">
          <div class="panel">
            <div class="panel-head"><h2>Token 构成</h2><span class="muted">官方 vs 中转</span></div>
            <canvas id="tokenChart" width="820" height="320"></canvas>
          </div>
          <div class="panel">
            <div class="panel-head"><h2>Token 明细</h2><span class="muted">按运行筛选</span></div>
            <div class="table-wrap"><table id="tokenTable"></table></div>
          </div>
        </div>
      </section>

      <section id="performance" class="section">
        <div class="panel">
          <div class="panel-head"><h2>性能和稳定性</h2><span class="muted">端到端耗时、验证耗时、错误</span></div>
          <div class="table-wrap"><table id="performanceTable"></table></div>
        </div>
      </section>

      <section id="benchmark" class="section">
        <div class="panel">
          <div class="panel-head"><h2>权威 Benchmark</h2><span class="muted" id="benchmarkStatus"></span></div>
          <div id="benchmarkBody"></div>
        </div>
      </section>

      <section id="details" class="section">
        <div class="panel">
          <div class="panel-head"><h2>运行明细</h2><span class="muted" id="detailCount"></span></div>
          <div class="table-wrap"><table id="runTable"></table></div>
        </div>
      </section>
    </main>
  </div>

  <script>
    const DATA = __APP_DATA__;
    const state = { tab: "overview", target: "all", search: "" };
    const tones = { good: "good", bad: "bad", warn: "warn", blue: "blue", violet: "violet" };

    function fmtPct(value) {
      if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
      let number = Number(value);
      if (Math.abs(number) <= 1) number *= 100;
      return `${number.toFixed(1)}%`;
    }
    function fmtInt(value) {
      if (value === null || value === undefined || value === "") return "n/a";
      return Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 0 });
    }
    function fmtSec(value) {
      if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
      return `${Number(value).toFixed(2)}s`;
    }
    function fmtNum(value, digits = 2) {
      if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
      return Number(value).toFixed(digits);
    }
    function esc(value) {
      return String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
    }
    function includesSearch(row) {
      if (!state.search) return true;
      return JSON.stringify(row).toLowerCase().includes(state.search.toLowerCase());
    }
    function targetMatches(row) {
      if (state.target === "all") return true;
      if (state.target === "failed") return row.passed === false || row.error || row.error_type;
      return row.target === state.target;
    }
    function status(passed) {
      return `<span class="status ${passed ? "pass" : "fail"}">${passed ? "PASS" : "FAIL"}</span>`;
    }
    function table(headers, rows, empty = "暂无数据") {
      const thead = `<thead><tr>${headers.map(item => `<th class="${item.cls || ""}">${esc(item.label)}</th>`).join("")}</tr></thead>`;
      const body = rows.length
        ? rows.join("")
        : `<tr><td colspan="${headers.length}"><div class="empty">${esc(empty)}</div></td></tr>`;
      return `${thead}<tbody>${body}</tbody>`;
    }
    function setSection(tab) {
      document.querySelectorAll(".section").forEach(section => section.classList.toggle("active", section.id === tab));
      document.querySelectorAll(".tab").forEach(button => button.classList.toggle("active", button.dataset.tab === tab));
      state.tab = tab;
      requestAnimationFrame(drawCharts);
    }
    function initHeader() {
      document.getElementById("pageTitle").textContent = DATA.meta.title;
      document.getElementById("pageSubtitle").textContent = `${DATA.meta.model || "unknown model"} · ${DATA.meta.gateway_url || "unknown gateway"}`;
      const items = [
        ["生成时间", DATA.meta.generated_at],
        ["编码运行", `${fmtInt(DATA.meta.coding_runs)} 次`],
        ["安全请求", `${fmtInt(DATA.meta.security_requests)} 次`],
        ["任务数", `${fmtInt(DATA.meta.task_count)} 个`],
      ];
      document.getElementById("metaStrip").innerHTML = items.map(([k, v]) => `<span class="pill">${esc(k)}：${esc(v)}</span>`).join("");
    }
    function renderCards() {
      document.getElementById("cards").innerHTML = DATA.cards.map(card => `
        <article class="card">
          <span class="label">${esc(card.label)}</span>
          <strong class="value ${tones[card.tone] || ""}">${esc(card.value)}</strong>
          <span class="detail">${esc(card.detail)}</span>
        </article>
      `).join("");
    }
    function renderQuality() {
      const rows = DATA.coding.task_rows.filter(includesSearch).map(row => `
        <tr>
          <td><strong>${esc(row.task_id)}</strong><div class="muted">${fmtInt(row.runs)} runs</div></td>
          <td class="num">${fmtPct(row.official_pass_rate)}</td>
          <td class="num">${fmtPct(row.gateway_pass_rate)}</td>
          <td class="num">${fmtPct(row.delta)}</td>
          <td class="num">${fmtSec(row.official_avg_duration)}</td>
          <td class="num">${fmtSec(row.gateway_avg_duration)}</td>
          <td class="num">${fmtInt(row.official_avg_tokens)}</td>
          <td class="num">${fmtInt(row.gateway_avg_tokens)}</td>
        </tr>
      `);
      document.getElementById("qualityCount").textContent = `${rows.length} 个任务`;
      document.getElementById("taskTable").innerHTML = table([
        { label: "任务" },
        { label: "官方通过率", cls: "num" },
        { label: "中转通过率", cls: "num" },
        { label: "差异", cls: "num" },
        { label: "官方耗时", cls: "num" },
        { label: "中转耗时", cls: "num" },
        { label: "官方 Token", cls: "num" },
        { label: "中转 Token", cls: "num" },
      ], rows);
    }
    function renderSecurity() {
      const provider = DATA.security.provider || {};
      const audit = DATA.security.audit_summary || {};
      const analysis = DATA.security.analysis || {};
      document.getElementById("securityBadge").textContent = `${fmtPct(provider.request_success_rate)} 请求成功率`;
      document.getElementById("securityOverview").innerHTML = [
        ["请求成功率", fmtPct(provider.request_success_rate), `${fmtInt(provider.request_success_count)}/${fmtInt(provider.total)}`],
        ["错误数", fmtInt(provider.error_count), Object.entries(provider.error_types || {}).map(([k, v]) => `${k}: ${v}`).join(" / ") || "-"],
        ["Canary 泄漏", fmtInt(analysis.canary_leakage_event_count || 0), "输出侧隐私探针"],
        ["Tamper 失败", fmtInt(analysis.tamper_probe_failure_count || 0), "异常多来自 HTTP/API 错误时需单独解释"],
        ["传输审计", `${fmtInt(audit.FAIL || 0)} FAIL`, `${fmtInt(audit.PASS || 0)} PASS / ${fmtInt(audit.WARN || 0)} WARN`],
      ].map(([name, value, detail]) => `
        <div class="list-item"><strong>${esc(name)}</strong><span class="muted">${esc(detail)}</span><span>${esc(value)}</span></div>
      `).join("");
      document.getElementById("auditSummary").textContent = `${fmtInt(audit.PASS)} PASS / ${fmtInt(audit.WARN)} WARN / ${fmtInt(audit.FAIL)} FAIL`;
      document.getElementById("auditTable").innerHTML = table([
        { label: "检查项" }, { label: "状态" }, { label: "证据" }, { label: "说明" },
      ], (DATA.security.audit_findings || []).filter(includesSearch).map(row => `
        <tr><td>${esc(row.check)}</td><td>${status(row.status === "PASS")}</td><td><code>${esc(row.evidence || "-")}</code></td><td>${esc(row.message || "-")}</td></tr>
      `));
      const failures = (DATA.security.failure_rows || []).filter(includesSearch);
      document.getElementById("failureCount").textContent = `${fmtInt(failures.length)} 条`;
      document.getElementById("securityFailureTable").innerHTML = table([
        { label: "Case" }, { label: "分类" }, { label: "错误类型" }, { label: "尝试", cls: "num" }, { label: "错误" },
      ], failures.map(row => `
        <tr><td><strong>${esc(row.case_id)}</strong></td><td>${esc(row.category)}</td><td>${esc(row.error_type || "-")}</td><td class="num">${fmtInt(row.attempts)}</td><td>${esc(row.error || "-")}</td></tr>
      `));
    }
    function renderTokens() {
      const runs = DATA.coding.run_rows.filter(row => targetMatches(row) && includesSearch(row));
      document.getElementById("tokenTable").innerHTML = table([
        { label: "任务" }, { label: "目标" }, { label: "状态" }, { label: "Total", cls: "num" }, { label: "Reasoning", cls: "num" }, { label: "耗时", cls: "num" },
      ], runs.map(row => `
        <tr><td>${esc(row.task_id)}</td><td>${esc(row.target)}</td><td>${status(row.passed)}</td><td class="num">${fmtInt(row.total_tokens)}</td><td class="num">${fmtInt(row.reasoning_tokens)}</td><td class="num">${fmtSec(row.duration)}</td></tr>
      `));
    }
    function renderPerformance() {
      const runs = DATA.coding.run_rows.filter(row => targetMatches(row) && includesSearch(row));
      document.getElementById("performanceTable").innerHTML = table([
        { label: "任务" }, { label: "目标" }, { label: "轮次", cls: "num" }, { label: "状态" }, { label: "Codex 耗时", cls: "num" }, { label: "验证耗时", cls: "num" }, { label: "改动文件" }, { label: "错误" },
      ], runs.map(row => `
        <tr><td>${esc(row.task_id)}</td><td>${esc(row.target)}</td><td class="num">${fmtInt(row.repeat_index)}</td><td>${status(row.passed)}</td><td class="num">${fmtSec(row.duration)}</td><td class="num">${fmtSec(row.verify_duration)}</td><td>${esc((row.changed_files || []).join(", ") || "-")}</td><td>${esc(row.error || "-")}</td></tr>
      `));
    }
    function renderBenchmark() {
      const benchmark = DATA.benchmark || {};
      const body = document.getElementById("benchmarkBody");
      if (benchmark.kind === "benchmark_plan") {
        document.getElementById("benchmarkStatus").textContent = `${benchmark.difficulty || "smoke"} 计划`;
        body.innerHTML = `<div class="table-wrap"><table>${table([
          { label: "Benchmark" }, { label: "方向" }, { label: "建议样本", cls: "num" }, { label: "运行状态" },
        ], (benchmark.suites || []).map(row => `
          <tr><td><strong>${esc(row.name)}</strong><div class="muted">${esc(row.benchmark)}</div></td><td>${esc(row.best_for)}</td><td class="num">${fmtInt(row.recommended_sample_size_per_target)}</td><td>${esc(row.adapter_status)}</td></tr>
        `))}</table></div>`;
      } else if (benchmark.kind === "benchmark_results") {
        document.getElementById("benchmarkStatus").textContent = "已导入";
        body.innerHTML = `<div class="table-wrap"><table>${table([
          { label: "目标" }, { label: "任务", cls: "num" }, { label: "通过率", cls: "num" }, { label: "平均分", cls: "num" }, { label: "平均耗时", cls: "num" },
        ], (benchmark.targets_summary || []).map(row => `
          <tr><td>${esc(row.target)}</td><td class="num">${fmtInt(row.tasks)}</td><td class="num">${fmtPct(row.pass_rate)}</td><td class="num">${fmtNum(row.avg_score, 3)}</td><td class="num">${fmtSec(row.avg_duration_seconds)}</td></tr>
        `))}</table></div>`;
      } else {
        document.getElementById("benchmarkStatus").textContent = "未导入";
        body.innerHTML = `<div class="empty">暂无 benchmark 计划或结果</div>`;
      }
    }
    function renderDetails() {
      const runs = DATA.coding.run_rows.filter(row => targetMatches(row) && includesSearch(row));
      document.getElementById("detailCount").textContent = `${fmtInt(runs.length)} 条`;
      document.getElementById("runTable").innerHTML = table([
        { label: "任务" }, { label: "目标" }, { label: "轮次", cls: "num" }, { label: "状态" }, { label: "耗时", cls: "num" }, { label: "Token", cls: "num" }, { label: "文件" },
      ], runs.map(row => `
        <tr><td>${esc(row.task_id)}</td><td>${esc(row.target)}</td><td class="num">${fmtInt(row.repeat_index)}</td><td>${status(row.passed)}</td><td class="num">${fmtSec(row.duration)}</td><td class="num">${fmtInt(row.total_tokens)}</td><td>${esc((row.changed_files || []).join(", ") || "-")}</td></tr>
      `));
    }
    function render() {
      renderCards();
      renderQuality();
      renderSecurity();
      renderTokens();
      renderPerformance();
      renderBenchmark();
      renderDetails();
      drawCharts();
    }
    function drawCharts() {
      drawGroupedBars("durationChart", DATA.coding.duration_chart.map(row => row.task_id), [
        { name: "官方", color: "#27618a", values: DATA.coding.duration_chart.map(row => row.official || 0) },
        { name: "中转", color: "#08746b", values: DATA.coding.duration_chart.map(row => row.gateway || 0) },
      ], "s");
      const errors = DATA.security.error_chart || [];
      drawBars("errorChart", errors.map(row => row.label), errors.map(row => row.value), "#b3261e", "");
      const tokenLabels = ["Input", "Cached", "Output", "Reasoning"];
      const tokenRows = DATA.coding.token_breakdown || [];
      drawGroupedBars("tokenChart", tokenLabels, tokenRows.map(row => ({
        name: row.target,
        color: row.target === "official" ? "#27618a" : "#08746b",
        values: tokenLabels.map(label => {
          const found = (row.values || []).find(item => item.label === label);
          return found ? found.value : 0;
        }),
      })), "");
    }
    function setupCanvas(canvas) {
      if (!canvas) return null;
      const rect = canvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.floor(rect.width * ratio));
      canvas.height = Math.max(1, Math.floor(rect.height * ratio));
      const ctx = canvas.getContext("2d");
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      return { ctx, width: rect.width, height: rect.height };
    }
    function drawGroupedBars(id, labels, series, unit) {
      const setup = setupCanvas(document.getElementById(id));
      if (!setup) return;
      const { ctx, width, height } = setup;
      ctx.clearRect(0, 0, width, height);
      if (!labels.length || !series.length) {
        drawEmpty(ctx, width, height);
        return;
      }
      const pad = { left: 54, right: 18, top: 34, bottom: 68 };
      const max = Math.max(1, ...series.flatMap(item => item.values));
      const plotW = width - pad.left - pad.right;
      const plotH = height - pad.top - pad.bottom;
      drawAxes(ctx, pad, width, height, max, unit);
      const groupW = plotW / labels.length;
      const barW = Math.min(28, (groupW - 16) / series.length);
      labels.forEach((label, i) => {
        series.forEach((item, j) => {
          const value = Number(item.values[i] || 0);
          const x = pad.left + i * groupW + groupW / 2 - (series.length * barW) / 2 + j * barW;
          const h = (value / max) * plotH;
          roundedRect(ctx, x, pad.top + plotH - h, barW - 3, h, 4, item.color);
        });
        ctx.fillStyle = "#5e6c76";
        ctx.font = "11px system-ui, sans-serif";
        ctx.textAlign = "right";
        ctx.save();
        ctx.translate(pad.left + i * groupW + groupW / 2, height - 42);
        ctx.rotate(-Math.PI / 5);
        ctx.fillText(String(label).slice(0, 16), 0, 0);
        ctx.restore();
      });
      series.forEach((item, i) => {
        roundedRect(ctx, pad.left + i * 92, 12, 12, 12, 3, item.color);
        ctx.fillStyle = "#172026";
        ctx.font = "12px system-ui, sans-serif";
        ctx.textAlign = "left";
        ctx.fillText(item.name, pad.left + 18 + i * 92, 23);
      });
    }
    function drawBars(id, labels, values, color, unit) {
      const setup = setupCanvas(document.getElementById(id));
      if (!setup) return;
      const { ctx, width, height } = setup;
      ctx.clearRect(0, 0, width, height);
      if (!labels.length) {
        drawEmpty(ctx, width, height);
        return;
      }
      const pad = { left: 52, right: 18, top: 28, bottom: 52 };
      const max = Math.max(1, ...values);
      const plotW = width - pad.left - pad.right;
      const plotH = height - pad.top - pad.bottom;
      drawAxes(ctx, pad, width, height, max, unit);
      const barW = Math.min(54, plotW / labels.length - 16);
      labels.forEach((label, i) => {
        const value = Number(values[i] || 0);
        const h = (value / max) * plotH;
        const x = pad.left + i * (plotW / labels.length) + (plotW / labels.length - barW) / 2;
        roundedRect(ctx, x, pad.top + plotH - h, barW, h, 5, color);
        ctx.fillStyle = "#172026";
        ctx.font = "12px system-ui, sans-serif";
        ctx.textAlign = "center";
        ctx.fillText(fmtInt(value), x + barW / 2, pad.top + plotH - h - 6);
        ctx.fillStyle = "#5e6c76";
        ctx.fillText(String(label).slice(0, 14), x + barW / 2, height - 22);
      });
    }
    function drawAxes(ctx, pad, width, height, max, unit) {
      const plotH = height - pad.top - pad.bottom;
      ctx.strokeStyle = "#d7e1df";
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (let i = 0; i <= 4; i += 1) {
        const y = pad.top + (plotH * i) / 4;
        ctx.moveTo(pad.left, y);
        ctx.lineTo(width - pad.right, y);
        const value = max * (1 - i / 4);
        ctx.fillStyle = "#5e6c76";
        ctx.font = "11px system-ui, sans-serif";
        ctx.textAlign = "right";
        ctx.fillText(`${fmtInt(value)}${unit}`, pad.left - 8, y + 4);
      }
      ctx.stroke();
    }
    function roundedRect(ctx, x, y, w, h, r, color) {
      const radius = Math.min(r, Math.abs(h) / 2, Math.abs(w) / 2);
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.moveTo(x + radius, y);
      ctx.arcTo(x + w, y, x + w, y + h, radius);
      ctx.arcTo(x + w, y + h, x, y + h, radius);
      ctx.arcTo(x, y + h, x, y, radius);
      ctx.arcTo(x, y, x + w, y, radius);
      ctx.closePath();
      ctx.fill();
    }
    function drawEmpty(ctx, width, height) {
      ctx.fillStyle = "#5e6c76";
      ctx.font = "14px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("暂无图表数据", width / 2, height / 2);
    }
    function bindControls() {
      document.querySelectorAll(".tab").forEach(button => button.addEventListener("click", () => setSection(button.dataset.tab)));
      document.querySelectorAll(".segment").forEach(button => button.addEventListener("click", () => {
        document.querySelectorAll(".segment").forEach(item => item.classList.toggle("active", item === button));
        state.target = button.dataset.target;
        renderTokens();
        renderPerformance();
        renderDetails();
      }));
      document.getElementById("searchBox").addEventListener("input", event => {
        state.search = event.target.value.trim();
        renderQuality();
        renderSecurity();
        renderTokens();
        renderPerformance();
        renderDetails();
      });
      window.addEventListener("resize", () => requestAnimationFrame(drawCharts));
    }
    initHeader();
    bindControls();
    render();
  </script>
</body>
</html>
"""
