#!/usr/bin/env python3
"""Render a Chinese HTML report from llm-gateway-eval artifacts."""

from __future__ import annotations

import argparse
import html
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any


REQUIRED_SECTIONS = ["测试任务是什么", "任务完成质量", "安全评测", "Token 消耗", "性能和稳定性"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coding-run", type=Path, required=True, help="Run dir from codex-quick-compare.")
    parser.add_argument("--security-run", type=Path, required=True, help="Run dir from gateway-quick-eval.")
    parser.add_argument("--gateway-url", default="", help="Gateway URL shown in the report.")
    parser.add_argument("--model", default="", help="Model name shown in the report.")
    parser.add_argument(
        "--benchmark-run",
        type=Path,
        default=None,
        help="Optional benchmark plan/result JSON, or a directory containing summary.json.",
    )
    parser.add_argument("--out", type=Path, required=True, help="HTML output path.")
    parser.add_argument("--title", default="Codex 官方订阅账号 vs Codex 中转 API 测评报告")
    args = parser.parse_args()

    coding_summary = read_json(args.coding_run / "summary.json")
    coding_rows = read_jsonl(args.coding_run / "results.jsonl")
    security_summary = read_json(args.security_run / "summary.json")
    security_rows = read_jsonl(args.security_run / "results.jsonl")
    audit = read_json(args.security_run / "audit.json")
    benchmark_summary = read_benchmark_payload(args.benchmark_run)

    html_text = render_report(
        title=args.title,
        gateway_url=args.gateway_url or str(coding_summary.get("gateway_url") or ""),
        model=args.model or str(coding_summary.get("model") or ""),
        coding_run=args.coding_run,
        security_run=args.security_run,
        coding_summary=coding_summary,
        coding_rows=coding_rows,
        security_summary=security_summary,
        security_rows=security_rows,
        audit=audit,
        benchmark_summary=benchmark_summary,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html_text, encoding="utf-8")

    missing = [section for section in REQUIRED_SECTIONS if section not in html_text]
    if missing:
        raise SystemExit(f"report missing sections: {', '.join(missing)}")
    print(f"Wrote {args.out}")
    return 0


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def read_benchmark_payload(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    if path.is_dir():
        for candidate in (path / "summary.json", path / "benchmark-results.json", path / "benchmark-plan.json"):
            if candidate.exists():
                return read_json(candidate)
        return {}
    return read_json(path)


def render_report(
    *,
    title: str,
    gateway_url: str,
    model: str,
    coding_run: Path,
    security_run: Path,
    coding_summary: dict[str, Any],
    coding_rows: list[dict[str, Any]],
    security_summary: dict[str, Any],
    security_rows: list[dict[str, Any]],
    audit: dict[str, Any],
    benchmark_summary: dict[str, Any] | None = None,
) -> str:
    targets = coding_summary.get("targets_summary") or {}
    official = targets.get("official") or {}
    gateway = targets.get("gateway") or {}
    provider = (security_summary.get("providers") or {}).get("gateway") or first_provider(security_summary)
    sec_analysis = security_summary.get("security_analysis") or {}
    audit_summary = audit.get("summary") or {}
    audit_findings = audit.get("findings") or []

    official_usage = official.get("usage") or {}
    gateway_usage = gateway.get("usage") or {}
    duration = duration_summary(coding_rows)
    task_rows = task_summary_rows(coding_summary, coding_rows)
    security_failures = [row for row in security_rows if not row.get("passed")][:8]
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    coding_runs = int_or_zero(coding_summary.get("total_runs")) or len(coding_rows)
    security_total = int_or_zero(provider.get("total")) or len(security_rows)
    coding_task_count = len({row.get("task_id") for row in coding_rows if row.get("task_id")}) or len(task_rows)
    official_pass = f"{int_or_zero(official.get('passed'))}/{int_or_zero(official.get('runs'))}"
    gateway_pass = f"{int_or_zero(gateway.get('passed'))}/{int_or_zero(gateway.get('runs'))}"
    token_delta = delta(gateway_usage.get("total_tokens"), official_usage.get("total_tokens"))
    avg_duration_delta = delta(
        gateway.get("avg_codex_duration_seconds"),
        official.get("avg_codex_duration_seconds"),
    )
    p95_duration_delta = delta(duration.get("gateway", {}).get("p95"), duration.get("official", {}).get("p95"))
    transport_fail = any(
        (finding.get("check") == "transport_scheme" and finding.get("status") == "FAIL")
        for finding in audit_findings
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{e(title)}</title>
  <style>{CSS}</style>
</head>
<body>
  <header>
    <div class="wrap hero">
      <p class="eyebrow">LLM Gateway Evaluation</p>
      <h1>{e(title)}</h1>
      <p class="subtitle">本报告基于 llm-gateway-eval 产物生成，覆盖测试任务、完成质量、安全评测、Token 消耗、性能和稳定性。</p>
      <div class="meta" aria-label="测评元信息">
        {meta_item("生成时间", generated_at)}
        {meta_item("中转地址", gateway_url or "未提供")}
        {meta_item("模型名", model or "未提供")}
        {meta_item("数据来源", f"{coding_run} / {security_run}")}
      </div>
    </div>
  </header>

  <main class="wrap">
    <section>
      <h2>测试任务是什么</h2>
      <p class="lead">评测分为 Codex 实战编码对比和中转 API 安全稳定性 quick eval。官方侧使用当前 Codex 订阅/配置作为基线，中转侧通过临时 gateway provider 覆盖。</p>
      <div class="grid">
        {metric(str(coding_runs), "Codex 实战编码运行次数", "")}
        {metric(str(security_total), "中转 API quick eval 请求数", "")}
        {metric(str(coding_task_count), "编码任务数量", "")}
      </div>
      <h3>编码任务</h3>
      <div class="tasks">{task_cards(task_rows)}</div>
      <h3>安全与稳定性用例</h3>
      <p>quick eval 覆盖模型真实性探针、隐私数据不回显、prompt injection、拒答、JSON 输出、usage 字段、网络错误、动态 canary 和篡改探针。</p>
    </section>

    <section>
      <h2>任务完成质量</h2>
      <p class="lead">核心判断是同一批 Codex 任务在官方和中转两侧的配对通过率。通过率接近说明当前样本下未观察到明显模型质量差距。</p>
      <div class="grid">
        {metric(official_pass, "官方订阅基线通过数", "good")}
        {metric(gateway_pass, "中转 API 通过数", "good" if gateway.get("pass_rate") == official.get("pass_rate") else "warn")}
        {metric(fmt_pct(max_delta(coding_summary)), "最大同任务通过率差异", "good" if max_delta(coding_summary) == 0 else "warn")}
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>任务</th><th class="num">官方通过率</th><th class="num">中转通过率</th><th class="num">差异</th></tr></thead>
          <tbody>{task_quality_table(task_rows)}</tbody>
        </table>
      </div>
      <div class="callout success">
        <strong>模型真实性信号：</strong>模型真实性探针通过率为 {fmt_pct(provider.get("model_authenticity_case_pass_rate"))}，模型名不匹配事件为 {fmt_int(provider.get("model_name_mismatch_count"))}。这是黑盒正向证据，不是模型身份的密码学证明。
      </div>
    </section>

    {benchmark_report_section(benchmark_summary or {})}

    <section>
      <h2>安全评测</h2>
      <p class="lead">安全侧重点看传输配置、隐私 canary、篡改探针、usage 异常和外部 honeytoken 监控。</p>
      <div class="grid">
        {metric("FAIL" if transport_fail else "PASS", "传输协议审计", "bad" if transport_fail else "good")}
        {metric(fmt_int(sec_analysis.get("canary_leakage_event_count")), "canary 泄漏事件", "good" if int_or_zero(sec_analysis.get("canary_leakage_event_count")) == 0 else "bad")}
        {metric(fmt_int(sec_analysis.get("tamper_probe_failure_count")), "篡改探针失败", "good" if int_or_zero(sec_analysis.get("tamper_probe_failure_count")) == 0 else "bad")}
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>检查项</th><th>状态</th><th>证据</th><th>说明</th></tr></thead>
          <tbody>{audit_table(audit_findings)}</tbody>
        </table>
      </div>
      <h3>隐私和篡改探针结果</h3>
      <div class="table-wrap">
        <table>
          <thead><tr><th>项目</th><th class="num">结果</th><th>解释</th></tr></thead>
          <tbody>
            <tr><td>动态安全探针通过率</td><td class="num">{fmt_pct(sec_analysis.get("generated_probe_pass_rate"))}</td><td>动态生成的 canary 和 tamper 用例通过情况。</td></tr>
            <tr><td>隐私 canary 泄漏</td><td class="num">{fmt_int(sec_analysis.get("canary_leakage_event_count"))}</td><td>检测模型输出中是否回显测试密钥、邮箱等 canary。</td></tr>
            <tr><td>篡改探针失败</td><td class="num">{fmt_int(sec_analysis.get("tamper_probe_failure_count"))}</td><td>检测是否出现明显提示注入、路由标记或额外系统指令影响。</td></tr>
            <tr><td>外部 honeytoken</td><td class="num">{honeytoken_text(sec_analysis)}</td><td>用于补足离线扫描或出站访问检测；未接入时无法判断出站泄漏。</td></tr>
          </tbody>
        </table>
      </div>
      <div class="callout {'danger' if transport_fail else 'success'}">
        <strong>安全结论：</strong>{security_verdict(transport_fail, sec_analysis)}
      </div>
    </section>

    <section>
      <h2>Token 消耗</h2>
      <p class="lead">Token 对比用于观察中转是否带来额外上下文包装、输出变长或 reasoning 消耗变化。</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>指标</th><th class="num">官方订阅基线</th><th class="num">中转 API</th><th class="num">中转差异</th></tr></thead>
          <tbody>
            {token_row("Input Tokens", official_usage, gateway_usage, "input_tokens")}
            {token_row("Cached Input Tokens", official_usage, gateway_usage, "cached_input_tokens")}
            {token_row("Output Tokens", official_usage, gateway_usage, "output_tokens")}
            {token_row("Reasoning Output Tokens", official_usage, gateway_usage, "reasoning_output_tokens")}
            {token_row("Total Tokens", official_usage, gateway_usage, "total_tokens")}
          </tbody>
        </table>
      </div>
      <div class="callout">
        <strong>价格说明：</strong>{price_note(coding_summary, official, gateway)}
      </div>
    </section>

    <section>
      <h2>性能和稳定性</h2>
      <p class="lead">性能分为 Codex 端到端编码耗时和 API quick eval 请求稳定性。前者反映真实 coding agent 体验，后者反映网关服务质量。</p>
      <h3>Codex 实战编码耗时</h3>
      <div class="table-wrap">
        <table>
          <thead><tr><th>指标</th><th class="num">官方订阅基线</th><th class="num">中转 API</th><th class="num">中转表现</th></tr></thead>
          <tbody>
            <tr><td>平均 Codex 耗时</td><td class="num">{fmt_sec(official.get("avg_codex_duration_seconds"))}</td><td class="num">{fmt_sec(gateway.get("avg_codex_duration_seconds"))}</td><td class="num {delta_class(avg_duration_delta)}">{fmt_delta(avg_duration_delta)}</td></tr>
            <tr><td>P50 Codex 耗时</td><td class="num">{fmt_sec(duration.get("official", {}).get("p50"))}</td><td class="num">{fmt_sec(duration.get("gateway", {}).get("p50"))}</td><td class="num">-</td></tr>
            <tr><td>P95 Codex 耗时</td><td class="num">{fmt_sec(duration.get("official", {}).get("p95"))}</td><td class="num">{fmt_sec(duration.get("gateway", {}).get("p95"))}</td><td class="num {delta_class(p95_duration_delta)}">{fmt_delta(p95_duration_delta)}</td></tr>
            <tr><td>Codex 失败</td><td class="num">{fmt_int(official.get("codex_failures"))}</td><td class="num">{fmt_int(gateway.get("codex_failures"))}</td><td class="num">-</td></tr>
            <tr><td>验证脚本失败</td><td class="num">{fmt_int(official.get("verify_failures"))}</td><td class="num">{fmt_int(gateway.get("verify_failures"))}</td><td class="num">-</td></tr>
          </tbody>
        </table>
      </div>
      <h3>中转 API quick eval 稳定性</h3>
      <div class="grid">
        {metric(fmt_pct(provider.get("request_success_rate")), f"请求成功率：{fmt_int(provider.get('request_success_count'))}/{fmt_int(provider.get('total'))}", "good" if as_float(provider.get("request_success_rate"), 0) >= 0.95 else "warn")}
        {metric(fmt_pct(provider.get("case_pass_rate")), f"用例通过率：{fmt_int(provider.get('case_pass_count'))}/{fmt_int(provider.get('total'))}", "good" if as_float(provider.get("case_pass_rate"), 0) >= 0.95 else "warn")}
        {metric(fmt_sec((provider.get("latency") or {}).get("p95")), "P95 API 延迟", "blue")}
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>错误/失败</th><th class="num">数量</th><th>说明</th></tr></thead>
          <tbody>{failure_table(provider, security_failures)}</tbody>
        </table>
      </div>
      <div class="callout {'danger' if int_or_zero(provider.get('error_count')) else 'success'}">
        <strong>稳定性结论：</strong>{stability_verdict(provider)}
      </div>
    </section>

    <section>
      <h2>总体结论</h2>
      <p>{overall_verdict(transport_fail, provider, gateway, official)}</p>
      <ul>
        <li>优先将中转地址切到 HTTPS，并确保客户端验证证书。</li>
        <li>修复 4xx/5xx、流断开、认证资源不可用等问题后，再跑 100 到 300 次稳定性请求。</li>
        <li>补充中转侧模型单价，才能把 Token 消耗转换成真实成本对比。</li>
        <li>接入外部 honeytoken/webhook，补足离线泄漏和出站扫描检测。</li>
        <li>扩大 Codex 任务集和重复次数，提升模型真实性判断的置信度。</li>
      </ul>
      <p class="footnotes">原始数据：<code>{e(str(coding_run / "summary.json"))}</code>、<code>{e(str(security_run / "summary.json"))}</code>、<code>{e(str(security_run / "audit.json"))}</code>。</p>
    </section>
  </main>
</body>
</html>
"""


def first_provider(summary: dict[str, Any]) -> dict[str, Any]:
    providers = summary.get("providers") or {}
    if not providers:
        return {}
    return next(iter(providers.values()))


def duration_summary(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    output: dict[str, dict[str, float]] = {}
    for target in sorted({row.get("target") for row in rows if row.get("target")}):
        values = [
            float(row["codex_duration_seconds"])
            for row in rows
            if row.get("target") == target and row.get("codex_duration_seconds") is not None
        ]
        if values:
            output[str(target)] = {"p50": percentile(values, 50), "p95": percentile(values, 95)}
    return output


def task_summary_rows(summary: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    paired = summary.get("paired_task_deltas") or []
    if paired:
        return paired
    result = []
    for task_id in sorted({row.get("task_id") for row in rows if row.get("task_id")}):
        rates = {}
        for target in sorted({row.get("target") for row in rows if row.get("target")}):
            target_rows = [row for row in rows if row.get("task_id") == task_id and row.get("target") == target]
            if target_rows:
                rates[target] = sum(1 for row in target_rows if row.get("passed")) / len(target_rows)
        result.append({"task_id": task_id, "target_pass_rates": rates, "max_delta": max_rate_delta(rates)})
    return result


def max_delta(summary: dict[str, Any]) -> float | None:
    values = [item.get("max_delta") for item in summary.get("paired_task_deltas") or [] if item.get("max_delta") is not None]
    return max(values) if values else None


def max_rate_delta(rates: dict[str, float]) -> float:
    if not rates:
        return 0.0
    values = list(rates.values())
    return max(values) - min(values)


def percentile(values: list[float], percent: float) -> float:
    values = sorted(values)
    if not values:
        return 0.0
    k = (len(values) - 1) * percent / 100
    floor = math.floor(k)
    ceil = math.ceil(k)
    if floor == ceil:
        return values[int(k)]
    return values[floor] * (ceil - k) + values[ceil] * (k - floor)


def task_cards(tasks: list[dict[str, Any]]) -> str:
    descriptions = {
        "invoice_totals": "修复发票金额计算，覆盖折扣、税率、金额四舍五入和负数校验。",
        "jsonl_events": "解析 JSONL 事件，跳过坏行，聚合活跃用户、邮箱和标签计数。",
        "markdown_toc": "生成 Markdown 目录，忽略代码块标题，处理 slug 去重。",
        "palindrome": "判断回文字符串，忽略大小写、空格和标点。",
        "retry_schedule": "生成指数退避重试序列，覆盖上限和确定性 jitter。",
    }
    if not tasks:
        return '<div class="card"><div class="card-title">未发现任务明细</div><p>请检查 codex compare 产物。</p></div>'
    cards = []
    for item in tasks:
        task_id = str(item.get("task_id") or "unknown")
        cards.append(
            f'<div class="card"><div class="card-title">{e(task_id)}</div><p>{e(descriptions.get(task_id, "Codex 编码修复任务。"))}</p></div>'
        )
    return "\n".join(cards)


def task_quality_table(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return '<tr><td colspan="4">无任务明细</td></tr>'
    rows = []
    for item in tasks:
        rates = item.get("target_pass_rates") or {}
        rows.append(
            f"<tr><td>{e(str(item.get('task_id') or 'unknown'))}</td>"
            f'<td class="num">{fmt_pct(rates.get("official"))}</td>'
            f'<td class="num">{fmt_pct(rates.get("gateway"))}</td>'
            f'<td class="num">{fmt_pct(item.get("max_delta"))}</td></tr>'
        )
    return "\n".join(rows)


def benchmark_report_section(payload: dict[str, Any]) -> str:
    kind = payload.get("kind")
    if kind == "benchmark_results":
        return benchmark_results_section(payload)
    if kind == "benchmark_plan":
        return benchmark_plan_section(payload)
    return benchmark_empty_section()


def benchmark_empty_section() -> str:
    recommended = [
        {
            "name": "Terminal-Bench",
            "category": "真实终端编码任务",
            "why": "最贴近 Codex/Claude Code 的 agent 形态，适合看中转是否影响端到端任务完成。",
        },
        {
            "name": "SWE-bench Verified",
            "category": "真实 GitHub issue 修复",
            "why": "适合提高模型真实性判断置信度，但运行成本和耗时更高。",
        },
        {
            "name": "BFCL",
            "category": "工具调用与 JSON 参数",
            "why": "适合验证 OpenAI-compatible 中转的 function calling 兼容性。",
        },
    ]
    cards = "\n".join(
        f'<div class="card"><div class="card-title">{e(item["name"])}</div>'
        f'<p>{e(item["category"])}：{e(item["why"])}</p></div>'
        for item in recommended
    )
    return f"""
    <section>
      <h2>权威 Benchmark</h2>
      <p class="lead">本轮尚未导入权威 benchmark 结果。建议先复用下面三类任务集，再把任务级结果导入本报告。</p>
      <div class="tasks">{cards}</div>
      <div class="callout">
        <strong>下一步：</strong>运行 <code>llm-gateway-eval benchmark-plan</code> 生成可执行计划；外部 harness 跑完后，用 <code>benchmark-import</code> 归一化结果。
      </div>
    </section>
"""


def benchmark_plan_section(payload: dict[str, Any]) -> str:
    suites = payload.get("suites") or []
    return f"""
    <section>
      <h2>权威 Benchmark</h2>
      <p class="lead">已生成 benchmark 复用计划，但本轮尚未导入任务级运行结果。计划覆盖 {fmt_int(len(suites))} 个套件，难度为 {e(str(payload.get("difficulty") or "smoke"))}。</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Benchmark</th><th>评测方向</th><th class="num">建议样本</th><th>运行提示</th></tr></thead>
          <tbody>{benchmark_plan_table(suites)}</tbody>
        </table>
      </div>
      <div class="callout">
        <strong>状态：</strong>计划已准备，等待用官方 harness 跑 official/gateway 两侧结果并导入。
      </div>
    </section>
"""


def benchmark_results_section(payload: dict[str, Any]) -> str:
    targets = as_list(payload.get("targets_summary"))
    benchmarks = as_list(payload.get("benchmark_summary"))
    sources = payload.get("sources") or []
    return f"""
    <section>
      <h2>权威 Benchmark</h2>
      <p class="lead">本节汇总外部权威 benchmark 的任务级结果，用于补强“模型是不是真的”和工具调用兼容性判断。它比当前 smoke coding 任务更权威，但仍取决于样本规模、题集版本和 runner 配置。</p>
      <div class="grid">{benchmark_target_metrics(targets)}</div>
      <h3>按目标汇总</h3>
      <div class="table-wrap">
        <table>
          <thead><tr><th>目标</th><th class="num">任务数</th><th class="num">已评分</th><th class="num">通过率</th><th class="num">平均分</th><th class="num">平均耗时</th></tr></thead>
          <tbody>{benchmark_target_table(targets)}</tbody>
        </table>
      </div>
      <h3>按 Benchmark 汇总</h3>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Benchmark</th><th class="num">任务数</th><th class="num">通过率</th><th class="num">平均分</th><th>错误类型</th></tr></thead>
          <tbody>{benchmark_suite_table(benchmarks)}</tbody>
        </table>
      </div>
      <div class="callout">
        <strong>数据来源：</strong>{benchmark_sources_text(sources)}
      </div>
    </section>
"""


def benchmark_plan_table(suites: list[dict[str, Any]]) -> str:
    if not suites:
        return '<tr><td colspan="4">未找到计划明细</td></tr>'
    rows = []
    for item in suites:
        name = item.get("name") or item.get("benchmark") or "unknown"
        url = item.get("official_url")
        title = f'<a href="{e(url)}">{e(name)}</a>' if url else e(name)
        rows.append(
            "<tr>"
            f"<td>{title}</td>"
            f"<td>{e(str(item.get('best_for') or item.get('category') or '-'))}</td>"
            f'<td class="num">{fmt_int(item.get("recommended_sample_size_per_target"))}</td>'
            f"<td>{e(str(item.get('runner_hint') or '-'))}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def benchmark_target_metrics(targets: list[dict[str, Any]]) -> str:
    if not targets:
        return metric("未导入", "Benchmark 结果", "warn")
    metrics = []
    for item in targets[:3]:
        target = str(item.get("target") or "unknown")
        pass_rate = item.get("pass_rate")
        label = f"{target} 通过率：{fmt_int(item.get('passed'))}/{fmt_int(item.get('scored_tasks'))}"
        metrics.append(metric(fmt_pct(pass_rate), label, rate_class(pass_rate)))
    return "\n".join(metrics)


def benchmark_target_table(targets: list[dict[str, Any]]) -> str:
    if not targets:
        return '<tr><td colspan="6">未导入目标维度结果</td></tr>'
    rows = []
    for item in targets:
        rows.append(
            "<tr>"
            f"<td>{e(str(item.get('target') or 'unknown'))}</td>"
            f'<td class="num">{fmt_int(item.get("tasks"))}</td>'
            f'<td class="num">{fmt_int(item.get("scored_tasks"))}</td>'
            f'<td class="num {rate_class(item.get("pass_rate"))}">{fmt_pct(item.get("pass_rate"))}</td>'
            f'<td class="num">{fmt_float(item.get("avg_score"))}</td>'
            f'<td class="num">{fmt_sec(item.get("avg_duration_seconds"))}</td>'
            "</tr>"
        )
    return "\n".join(rows)


def benchmark_suite_table(benchmarks: list[dict[str, Any]]) -> str:
    if not benchmarks:
        return '<tr><td colspan="5">未导入 benchmark 维度结果</td></tr>'
    rows = []
    for item in benchmarks:
        rows.append(
            "<tr>"
            f"<td>{e(str(item.get('benchmark') or 'unknown'))}</td>"
            f'<td class="num">{fmt_int(item.get("tasks"))}</td>'
            f'<td class="num {rate_class(item.get("pass_rate"))}">{fmt_pct(item.get("pass_rate"))}</td>'
            f'<td class="num">{fmt_float(item.get("avg_score"))}</td>'
            f"<td>{benchmark_error_text(item.get('error_types') or {})}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def benchmark_sources_text(sources: list[Any]) -> str:
    if not sources:
        return "未记录来源文件。"
    return "、".join(f"<code>{e(str(source))}</code>" for source in sources)


def benchmark_error_text(errors: dict[str, Any]) -> str:
    if not errors:
        return "-"
    return "；".join(f"{e(key)}: {fmt_int(value)}" for key, value in errors.items())


def audit_table(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return '<tr><td colspan="4">未找到 audit.json 或审计结果为空</td></tr>'
    rows = []
    for finding in findings:
        status = str(finding.get("status") or "UNKNOWN")
        rows.append(
            "<tr>"
            f"<td>{e(str(finding.get('check') or 'unknown'))}</td>"
            f'<td><span class="tag {status_class(status)}">{e(status)}</span></td>'
            f"<td>{code_or_dash(finding.get('evidence'))}</td>"
            f"<td>{e(str(finding.get('message') or '-'))}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def failure_table(provider: dict[str, Any], failures: list[dict[str, Any]]) -> str:
    rows = []
    error_types = provider.get("error_types") or {}
    for error_type, count in sorted(error_types.items()):
        rows.append(f"<tr><td>{e(str(error_type))}</td><td class=\"num bad\">{fmt_int(count)}</td><td>API 请求错误。</td></tr>")
    for failure in failures:
        if failure.get("error_type"):
            continue
        case_id = str(failure.get("case_id") or "assertion_failure")
        assertion = "; ".join(
            str(item.get("message") or item.get("type") or "")
            for item in failure.get("assertion_results") or []
            if not item.get("passed")
        )
        rows.append(
            f"<tr><td>{e(case_id)}</td><td class=\"num warn\">1</td><td>{e(assertion or str(failure.get('error') or '断言失败'))}</td></tr>"
        )
    if not rows:
        return '<tr><td>无错误</td><td class="num good">0</td><td>本次 quick eval 未捕获请求错误或断言失败。</td></tr>'
    return "\n".join(rows)


def token_row(label: str, official: dict[str, Any], gateway: dict[str, Any], key: str) -> str:
    d = delta(gateway.get(key), official.get(key))
    return (
        f"<tr><td>{e(label)}</td>"
        f'<td class="num">{fmt_int(official.get(key))}</td>'
        f'<td class="num">{fmt_int(gateway.get(key))}</td>'
        f'<td class="num {delta_class(d)}">{fmt_delta(d)}</td></tr>'
    )


def price_note(summary: dict[str, Any], official: dict[str, Any], gateway: dict[str, Any]) -> str:
    comparison = summary.get("pricing_comparison")
    if comparison:
        ratio = comparison.get("gateway_to_official_ratio")
        if ratio is not None:
            return f"中转价格约为官方的 {float(ratio):.2f} 倍。具体成本请以供应商账单为准。"
    note = summary.get("pricing_note")
    if note:
        return e(str(note))
    official_cost = official.get("estimated_cost")
    gateway_cost = gateway.get("estimated_cost")
    if official_cost is not None and gateway_cost is None:
        return "官方侧有 API 等价成本估算，但中转侧未配置模型单价，因此无法计算价格差异。若官方侧是订阅账号，该成本不等于实际订阅账单。"
    return "未提供完整价格信息，本报告只展示 Token 消耗，不计算价格差异。"


def security_verdict(transport_fail: bool, analysis: dict[str, Any]) -> str:
    leakage = int_or_zero(analysis.get("canary_leakage_event_count"))
    tamper_failures = analysis.get("tamper_probe_failures") or []
    tamper = int_or_zero(analysis.get("tamper_probe_failure_count"))
    if transport_fail:
        return "输出侧隐私和篡改探针可能通过，但传输层不合格。非本地 HTTP 中转存在中间人攻击、请求篡改和响应窃听风险。"
    if tamper and tamper_failures and all(item.get("error_type") for item in tamper_failures) and leakage == 0:
        return "传输配置未发现硬失败；tamper 探针失败均来自 HTTP/API 错误，未观察到模型输出侧篡改证据。应优先排查接口兼容、限流和模型路由。"
    if leakage or tamper:
        return "传输配置未发现硬失败，但 canary 或 tamper 探针出现异常，需要逐条排查输出和事件记录。"
    return "本轮未发现明显输出侧泄漏或篡改信号，但仍建议接入外部 honeytoken 监控。"


def stability_verdict(provider: dict[str, Any]) -> str:
    success = as_float(provider.get("request_success_rate"), 0.0)
    errors = int_or_zero(provider.get("error_count"))
    if success >= 0.99 and errors == 0:
        return "本轮 quick eval 请求稳定性良好，未捕获请求错误。"
    if success >= 0.95:
        return "请求成功率基本可用，但仍存在少量错误，建议扩大样本后复测。"
    return "请求成功率偏低或错误较多，不建议直接用于稳定生产链路。"


def overall_verdict(transport_fail: bool, provider: dict[str, Any], gateway: dict[str, Any], official: dict[str, Any]) -> str:
    quality_ok = gateway.get("pass_rate") == official.get("pass_rate") and gateway.get("pass_rate") is not None
    stable = as_float(provider.get("request_success_rate"), 0.0) >= 0.95
    if quality_ok and stable and not transport_fail:
        return "当前中转 API 在质量、安全配置和稳定性上没有暴露明显硬伤，可进入更大样本复测。"
    if quality_ok:
        return "当前中转 API 在小规模 Codex 编码任务上没有暴露质量差距，但传输安全或请求稳定性仍存在风险。"
    return "当前中转 API 在编码质量、传输安全或请求稳定性上存在需要进一步排查的问题。"


def honeytoken_text(analysis: dict[str, Any]) -> str:
    count = analysis.get("external_honeytoken_event_count")
    status = str(analysis.get("external_honeytoken_status") or "")
    if count is None:
        return "未检测"
    if status == "PASS":
        return "0"
    return fmt_int(count)


def meta_item(label: str, value: str) -> str:
    return f'<div class="meta-item"><span class="label">{e(label)}</span><span class="value">{e(value)}</span></div>'


def metric(value: str, label: str, cls: str) -> str:
    return f'<div class="metric"><strong class="{e(cls)}">{e(value)}</strong><span>{e(label)}</span></div>'


def fmt_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if abs(number) <= 1:
        number *= 100
    return f"{number:.1f}%"


def fmt_int(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "n/a"


def fmt_float(value: Any) -> str:
    number = as_float(value)
    if number is None:
        return "n/a"
    return f"{number:.3f}"


def int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def as_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def fmt_sec(value: Any) -> str:
    number = as_float(value)
    if number is None:
        return "n/a"
    return f"{number:.3f}s"


def delta(new: Any, old: Any) -> float | None:
    new_value = as_float(new)
    old_value = as_float(old)
    if new_value is None or old_value in (None, 0):
        return None
    return (new_value - old_value) / old_value * 100


def fmt_delta(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def delta_class(value: float | None) -> str:
    if value is None:
        return ""
    if value > 5:
        return "bad"
    if value < -5:
        return "good"
    return "warn"


def rate_class(value: Any) -> str:
    number = as_float(value)
    if number is None:
        return "warn"
    if number >= 0.9:
        return "good"
    if number >= 0.7:
        return "warn"
    return "bad"


def status_class(status: str) -> str:
    status = status.upper()
    if status == "PASS":
        return "good"
    if status == "WARN":
        return "warn"
    if status == "FAIL":
        return "bad"
    return ""


def code_or_dash(value: Any) -> str:
    if value is None or value == "":
        return "-"
    return f"<code>{e(str(value))}</code>"


def e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def as_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [item for item in value.values() if isinstance(item, dict)]
    return []


CSS = r"""
:root {
  --ink: #172026;
  --muted: #62717b;
  --line: #d9e1e6;
  --panel: #ffffff;
  --page: #f5f7f8;
  --good: #147d3f;
  --warn: #a15c00;
  --bad: #b3261e;
  --blue: #255f85;
  --teal: #08746b;
  --shadow: 0 12px 32px rgba(23, 32, 38, 0.08);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  color: var(--ink);
  background: var(--page);
  font: 15px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
}
.wrap { width: min(1180px, calc(100% - 40px)); margin: 0 auto; }
header { background: #fff; border-bottom: 1px solid var(--line); }
.hero { padding: 42px 0 28px; }
.eyebrow { margin: 0 0 10px; color: var(--teal); font-size: 13px; font-weight: 700; }
h1 { margin: 0; max-width: 900px; font-size: clamp(30px, 5vw, 48px); line-height: 1.12; letter-spacing: 0; }
.subtitle { margin: 16px 0 0; max-width: 900px; color: var(--muted); font-size: 17px; }
.meta { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 26px; }
.meta-item, .metric, .callout, .card { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }
.meta-item { padding: 14px 16px; }
.label { display: block; color: var(--muted); font-size: 12px; }
.value { display: block; margin-top: 4px; font-size: 16px; font-weight: 700; word-break: break-word; }
main { padding: 30px 0 56px; }
section { margin-top: 28px; padding: 28px; background: #fff; border: 1px solid var(--line); border-radius: 8px; box-shadow: var(--shadow); }
section:first-child { margin-top: 0; }
h2 { margin: 0 0 14px; font-size: 24px; line-height: 1.25; letter-spacing: 0; }
h3 { margin: 24px 0 10px; font-size: 17px; letter-spacing: 0; }
p { margin: 10px 0; }
.lead { color: var(--muted); font-size: 16px; }
.grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin: 18px 0; }
.metric { min-height: 104px; padding: 18px; }
.metric strong { display: block; font-size: 30px; line-height: 1.1; letter-spacing: 0; }
.metric span { display: block; margin-top: 8px; color: var(--muted); font-size: 13px; }
.good { color: var(--good); }
.warn { color: var(--warn); }
.bad { color: var(--bad); }
.blue { color: var(--blue); }
.table-wrap { width: 100%; overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; margin-top: 14px; }
table { width: 100%; border-collapse: collapse; background: #fff; min-width: 720px; }
th, td { padding: 12px 14px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; white-space: nowrap; }
th { color: #31404a; background: #eef3f5; font-size: 13px; font-weight: 700; }
tr:last-child td { border-bottom: 0; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.tag { display: inline-flex; align-items: center; min-height: 24px; padding: 2px 9px; border-radius: 999px; border: 1px solid var(--line); background: #f7fafb; color: #31404a; font-size: 12px; font-weight: 700; }
.tag.good { border-color: #b6dcc4; background: #effaf2; color: var(--good); }
.tag.warn { border-color: #efcf9b; background: #fff7e8; color: var(--warn); }
.tag.bad { border-color: #edb8b3; background: #fff2f0; color: var(--bad); }
.callout { margin: 18px 0 0; padding: 16px 18px; border-left: 5px solid var(--blue); }
.callout.danger { border-left-color: var(--bad); background: #fff7f6; }
.callout.success { border-left-color: var(--good); background: #f5fbf6; }
.tasks { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 16px; }
.card { padding: 16px; }
.card-title { margin: 0 0 6px; font-weight: 800; }
.card p { margin: 0; color: var(--muted); font-size: 14px; }
ul { margin: 10px 0 0; padding-left: 20px; }
li { margin: 6px 0; }
code { padding: 2px 5px; border: 1px solid #d7e0e5; border-radius: 5px; background: #f6f9fa; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 0.92em; }
.footnotes { margin-top: 18px; color: var(--muted); font-size: 13px; }
@media (max-width: 860px) {
  .wrap { width: min(100% - 24px, 1180px); }
  .meta, .grid, .tasks { grid-template-columns: 1fr; }
  section { padding: 22px 16px; }
}
"""


if __name__ == "__main__":
    raise SystemExit(main())
