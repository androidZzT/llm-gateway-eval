from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


class BenchmarkError(ValueError):
    """Raised when benchmark plans or imported artifacts are invalid."""


SUPPORTED_BENCHMARKS: dict[str, dict[str, Any]] = {
    "terminal-bench": {
        "name": "Terminal-Bench",
        "category": "coding_agent_terminal",
        "official_url": "https://github.com/laude-institute/terminal-bench",
        "best_for": "检验 Codex/Claude Code 类 agent 在真实终端任务中的端到端完成能力。",
        "runner_hint": "用官方 Terminal-Bench harness 分别跑 official 与 gateway target，再导出 JSON/JSONL/CSV。",
        "primary_metrics": ["pass_rate", "task_success", "duration_seconds"],
    },
    "swe-bench-verified": {
        "name": "SWE-bench Verified",
        "category": "coding_agent_repository",
        "official_url": "https://www.swebench.com/",
        "best_for": "检验真实 GitHub issue 修复能力，适合评估模型是否被降级或替换。",
        "runner_hint": "用 SWE-bench Verified 子集跑官方和中转模型，导入 instance_id/resolved/score 字段。",
        "primary_metrics": ["resolved_rate", "pass_rate", "duration_seconds"],
    },
    "bfcl": {
        "name": "Berkeley Function Calling Leaderboard",
        "category": "tool_calling",
        "official_url": "https://gorilla.cs.berkeley.edu/leaderboard.html",
        "best_for": "检验 OpenAI-compatible 工具调用、JSON/参数生成和多轮函数调用兼容性。",
        "runner_hint": "用 BFCL 官方评测脚本跑工具调用结果，导入 id/success/score 字段。",
        "primary_metrics": ["accuracy", "pass_rate"],
    },
    "bigcodebench-hard": {
        "name": "BigCodeBench-Hard",
        "category": "code_generation",
        "official_url": "https://github.com/bigcode-project/bigcodebench",
        "best_for": "检验函数级代码生成与复杂编程题质量。",
        "runner_hint": "用 BigCodeBench/BigCodeBench-Hard harness 跑 pass@1 或 score，再导入任务级结果。",
        "primary_metrics": ["pass_at_1", "score"],
    },
    "livecodebench": {
        "name": "LiveCodeBench",
        "category": "code_generation",
        "official_url": "https://livecodebench.github.io/",
        "best_for": "检验较新编程题上的泛化能力，减少训练集污染带来的误判。",
        "runner_hint": "选择固定时间窗和题集版本，分别跑 official/gateway 后导入 pass/score。",
        "primary_metrics": ["pass_rate", "score"],
    },
    "cyberseceval": {
        "name": "CyberSecEval",
        "category": "security",
        "official_url": "https://github.com/meta-llama/PurpleLlama",
        "best_for": "检验安全合规、危险请求拒答和代码安全相关能力。",
        "runner_hint": "用 PurpleLlama/CyberSecEval 生成任务级结果，导入 pass/score 和安全分类。",
        "primary_metrics": ["safe_rate", "pass_rate", "score"],
    },
}

DEFAULT_BENCHMARK_SUITES = ["terminal-bench", "swe-bench-verified", "bfcl"]
ACCEPTED_RESULT_FORMATS = ["json", "jsonl", "csv"]
REQUIRED_IMPORT_FIELDS = ["task_id 或 id/instance_id/problem_id", "target 或 --target", "passed/success/resolved 或 score"]
RECOMMENDED_IMPORT_FIELDS = ["duration_seconds", "difficulty", "error", "model", "tokens"]


def build_benchmark_plan(
    suites: list[str] | None = None,
    *,
    sample_size: int = 20,
    difficulty: str = "smoke",
) -> dict[str, Any]:
    if sample_size < 1:
        raise BenchmarkError("sample_size must be at least 1.")
    selected = _validate_suites(suites or DEFAULT_BENCHMARK_SUITES)
    entries = []
    for benchmark_id in selected:
        meta = SUPPORTED_BENCHMARKS[benchmark_id]
        entries.append(
            {
                "benchmark": benchmark_id,
                "name": meta["name"],
                "category": meta["category"],
                "official_url": meta["official_url"],
                "best_for": meta["best_for"],
                "difficulty": difficulty,
                "recommended_sample_size_per_target": sample_size,
                "selection_strategy": _selection_strategy(difficulty),
                "adapter_status": "external_runner_required",
                "runner_hint": meta["runner_hint"],
                "primary_metrics": meta["primary_metrics"],
                "result_import": {
                    "accepted_formats": ACCEPTED_RESULT_FORMATS,
                    "required_fields": REQUIRED_IMPORT_FIELDS,
                    "recommended_fields": RECOMMENDED_IMPORT_FIELDS,
                },
            }
        )
    return {
        "schema_version": 1,
        "kind": "benchmark_plan",
        "status": "planned",
        "generated_at": _now(),
        "difficulty": difficulty,
        "recommended_targets": ["official", "gateway"],
        "suites": entries,
        "next_steps": [
            "用官方 benchmark harness 分别跑 official 与 gateway。",
            "将任务级结果导出为 JSON、JSONL 或 CSV。",
            "用 llm-gateway-eval benchmark-import 归一化结果，并在 HTML 报告中引用。",
        ],
    }


def import_benchmark_results(
    input_path: Path,
    *,
    benchmark: str,
    target: str | None = None,
    existing_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _validate_suites([benchmark])
    rows = _load_rows(input_path)
    normalized = [
        normalize_benchmark_row(row, benchmark=benchmark, default_target=target, source_path=input_path, row_number=index)
        for index, row in enumerate(rows, start=1)
    ]
    if not normalized:
        raise BenchmarkError(f"No benchmark result rows found in {input_path}.")

    existing_results = list((existing_summary or {}).get("results") or [])
    results = [*existing_results, *normalized]
    sources = list((existing_summary or {}).get("sources") or [])
    source_text = str(input_path)
    if source_text not in sources:
        sources.append(source_text)
    return summarize_benchmark_results(results, sources=sources)


def normalize_benchmark_row(
    row: dict[str, Any],
    *,
    benchmark: str,
    default_target: str | None,
    source_path: Path,
    row_number: int,
) -> dict[str, Any]:
    task_id = _first_present(
        row,
        "task_id",
        "instance_id",
        "problem_id",
        "id",
        "name",
        "test_name",
        "question_id",
    )
    if task_id in (None, ""):
        raise BenchmarkError(f"{source_path}:{row_number} missing task_id/id/instance_id.")

    target = default_target or _first_present(row, "target", "provider", "model_target", "runner", "system")
    if target in (None, ""):
        raise BenchmarkError(f"{source_path}:{row_number} missing target. Pass --target or include a target field.")

    score = _parse_float(_first_present(row, "score", "accuracy", "pass_rate", "resolved_rate", "pass_at_1"))
    passed = _parse_bool(
        _first_present(
            row,
            "passed",
            "pass",
            "success",
            "successful",
            "resolved",
            "is_correct",
            "exact_match",
        )
    )
    if passed is None and score is not None and score in {0.0, 1.0}:
        passed = score == 1.0
    if score is None and passed is not None:
        score = 1.0 if passed else 0.0

    duration = _parse_float(
        _first_present(row, "duration_seconds", "elapsed_seconds", "latency_seconds", "wall_time", "time_seconds")
    )
    error = _first_present(row, "error", "failure", "exception", "message")
    status = _first_present(row, "status", "result")
    if passed is False and not error and status:
        error = status

    return {
        "benchmark": benchmark,
        "suite": str(_first_present(row, "suite", "subset", "split") or benchmark),
        "task_id": str(task_id),
        "target": str(target),
        "passed": passed,
        "score": score,
        "duration_seconds": duration,
        "difficulty": _optional_str(_first_present(row, "difficulty", "level", "category")),
        "model": _optional_str(_first_present(row, "model", "model_name", "requested_model")),
        "error": _optional_str(error),
        "source": {
            "path": str(source_path),
            "row_number": row_number,
        },
    }


def summarize_benchmark_results(results: list[dict[str, Any]], *, sources: list[str] | None = None) -> dict[str, Any]:
    target_summaries = [
        _summary_for_rows({"target": target}, target_rows)
        for target, target_rows in sorted(_group_by(results, "target").items())
    ]
    benchmark_summaries = [
        _summary_for_rows({"benchmark": benchmark}, benchmark_rows)
        for benchmark, benchmark_rows in sorted(_group_by(results, "benchmark").items())
    ]
    return {
        "schema_version": 1,
        "kind": "benchmark_results",
        "status": "ready" if results else "empty",
        "generated_at": _now(),
        "sources": sources or [],
        "results": results,
        "targets_summary": target_summaries,
        "benchmark_summary": benchmark_summaries,
    }


def parse_suite_csv(value: str) -> list[str]:
    suites = [item.strip() for item in value.split(",") if item.strip()]
    if not suites:
        raise BenchmarkError("At least one benchmark suite is required.")
    return suites


def _summary_for_rows(identity: dict[str, str], rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [row for row in rows if row.get("passed") is not None]
    passed = sum(1 for row in scored if row.get("passed") is True)
    failed = sum(1 for row in scored if row.get("passed") is False)
    scores = [float(row["score"]) for row in rows if row.get("score") is not None]
    durations = [float(row["duration_seconds"]) for row in rows if row.get("duration_seconds") is not None]
    errors = Counter(str(row.get("error")) for row in rows if row.get("error"))
    return {
        **identity,
        "tasks": len(rows),
        "scored_tasks": len(scored),
        "passed": passed,
        "failed": failed,
        "unknown": len(rows) - len(scored),
        "pass_rate": passed / len(scored) if scored else None,
        "avg_score": sum(scores) / len(scores) if scores else None,
        "avg_duration_seconds": sum(durations) / len(durations) if durations else None,
        "error_types": dict(sorted(errors.items())),
    }


def _load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise BenchmarkError(f"missing benchmark result input: {path}")
    if path.is_dir():
        rows: list[dict[str, Any]] = []
        for child in sorted(path.iterdir()):
            if child.suffix.lower().lstrip(".") in ACCEPTED_RESULT_FORMATS:
                rows.extend(_load_rows(child))
        return rows

    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        return _load_jsonl(path)
    if suffix == ".json":
        return _load_json(path)
    if suffix == ".csv":
        return _load_csv(path)
    raise BenchmarkError(f"Unsupported benchmark result format: {path.suffix}")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BenchmarkError(f"{path}:{line_number} invalid JSONL: {exc}") from exc
        if not isinstance(row, dict):
            raise BenchmarkError(f"{path}:{line_number} must be a JSON object.")
        rows.append(row)
    return rows


def _load_json(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = None
        for key in ("results", "rows", "tasks", "instances", "examples"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                rows = candidate
                break
        if rows is None:
            rows = [payload]
    else:
        raise BenchmarkError(f"{path} must contain a JSON object or list.")
    if not all(isinstance(row, dict) for row in rows):
        raise BenchmarkError(f"{path} result rows must be JSON objects.")
    return list(rows)


def _load_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _validate_suites(suites: list[str]) -> list[str]:
    unknown = [suite for suite in suites if suite not in SUPPORTED_BENCHMARKS]
    if unknown:
        supported = ", ".join(sorted(SUPPORTED_BENCHMARKS))
        raise BenchmarkError(f"Unsupported benchmark suite(s): {', '.join(unknown)}. Supported: {supported}.")
    return suites


def _group_by(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "unknown")].append(row)
    return grouped


def _selection_strategy(difficulty: str) -> str:
    if difficulty == "full":
        return "full_suite_or_official_verified_subset"
    if difficulty in {"hard", "confidence"}:
        return "stratified_sample_high_signal_tasks"
    return "small_stratified_smoke_sample"


def _first_present(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        if value == 1:
            return True
        if value == 0:
            return False
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "t", "yes", "y", "1", "pass", "passed", "success", "successful", "resolved", "ok"}:
            return True
        if normalized in {"false", "f", "no", "n", "0", "fail", "failed", "failure", "unresolved", "error"}:
            return False
    return None


def _parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
