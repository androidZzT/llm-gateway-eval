from __future__ import annotations

import json
import shutil
import subprocess
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .pricing import TokenPricing, calculate_token_cost


@dataclass(frozen=True)
class CodexCompareTarget:
    name: str
    profile: str | None = None
    config_overrides: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    pricing: TokenPricing | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "profile": self.profile,
            "config_overrides": self.config_overrides,
            "env_keys": sorted(self.env),
            "pricing": None if self.pricing is None else self.pricing.to_dict(),
        }


@dataclass(frozen=True)
class CodexTask:
    id: str
    path: Path
    repo_path: Path
    prompt_path: Path
    verify_command: str


@dataclass(frozen=True)
class CodexRunResult:
    task_id: str
    target: str
    profile: str | None
    repeat_index: int
    workspace: str
    codex_exit_code: int
    verify_exit_code: int | None
    passed: bool
    codex_duration_seconds: float
    verify_duration_seconds: float | None
    patch_path: str
    changed_files: list[str]
    error: str | None
    usage: dict[str, int]
    estimated_cost: float | None
    currency: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CodexCompareError(ValueError):
    pass


def discover_tasks(
    tasks_dir: str | Path,
    prompt_file: str = "TASK.md",
    verify_command: str = "bash ./verify.sh",
) -> list[CodexTask]:
    root = Path(tasks_dir)
    if not root.exists():
        raise CodexCompareError(f"Tasks directory does not exist: {root}")

    tasks: list[CodexTask] = []
    for task_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        repo_path = task_dir / "repo"
        prompt_path = task_dir / prompt_file
        if not repo_path.is_dir() or not prompt_path.is_file():
            continue
        tasks.append(
            CodexTask(
                id=task_dir.name,
                path=task_dir,
                repo_path=repo_path,
                prompt_path=prompt_path,
                verify_command=verify_command,
            )
        )

    if not tasks:
        raise CodexCompareError(
            f"No tasks found in {root}. Expected subdirectories containing repo/ and {prompt_file}."
        )
    return tasks


def run_codex_compare(
    tasks: list[CodexTask],
    targets: list[CodexCompareTarget],
    repeats: int,
    out_dir: str | Path,
    codex_bin: str = "codex",
    timeout_seconds: int = 1800,
    extra_codex_args: list[str] | None = None,
) -> tuple[list[CodexRunResult], dict[str, Any]]:
    output_root = Path(out_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    results: list[CodexRunResult] = []

    for target in targets:
        for task in tasks:
            for repeat_index in range(1, repeats + 1):
                result = _run_single(
                    task=task,
                    target=target,
                    repeat_index=repeat_index,
                    output_root=output_root,
                    codex_bin=codex_bin,
                    timeout_seconds=timeout_seconds,
                    extra_codex_args=extra_codex_args or [],
                )
                results.append(result)

    summary = summarize_codex_results(results)
    summary["generated_at"] = datetime.now(timezone.utc).isoformat()
    summary["task_count"] = len(tasks)
    summary["targets"] = [target.public_dict() for target in targets]
    summary["repeats"] = repeats
    summary["codex_bin"] = codex_bin
    return results, summary


def write_codex_compare_outputs(
    results: list[CodexRunResult],
    summary: dict[str, Any],
    out_dir: str | Path,
) -> tuple[Path, Path]:
    output_root = Path(out_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    results_path = output_root / "results.jsonl"
    summary_path = output_root / "summary.json"
    results_path.write_text(
        "\n".join(json.dumps(result.to_dict(), ensure_ascii=False) for result in results) + "\n",
        encoding="utf-8",
    )
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return results_path, summary_path


def summarize_codex_results(results: list[CodexRunResult]) -> dict[str, Any]:
    by_target: dict[str, list[CodexRunResult]] = defaultdict(list)
    by_task: dict[str, list[CodexRunResult]] = defaultdict(list)
    for result in results:
        by_target[result.target].append(result)
        by_task[result.task_id].append(result)

    targets_summary = {
        target: _summarize_group(items)
        for target, items in sorted(by_target.items())
    }
    return {
        "total_runs": len(results),
        "overall_pass_rate": _rate(sum(1 for result in results if result.passed), len(results)),
        "targets_summary": targets_summary,
        "pricing_comparison": _pricing_comparison(targets_summary),
        "tasks_summary": {
            task_id: _summarize_group(items)
            for task_id, items in sorted(by_task.items())
        },
        "paired_task_deltas": _paired_task_deltas(by_task),
    }


def _run_single(
    task: CodexTask,
    target: CodexCompareTarget,
    repeat_index: int,
    output_root: Path,
    codex_bin: str,
    timeout_seconds: int,
    extra_codex_args: list[str],
) -> CodexRunResult:
    workspace = output_root / "workspaces" / target.name / task.id / f"run-{repeat_index}"
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(task.repo_path, workspace)
    _ensure_git_baseline(workspace)
    _exclude_runner_artifacts(workspace)

    prompt = task.prompt_path.read_text(encoding="utf-8")
    codex_stdout = workspace / "codex-events.jsonl"
    codex_stderr = workspace / "codex-stderr.txt"
    verify_stdout = workspace / "verify-stdout.txt"
    verify_stderr = workspace / "verify-stderr.txt"
    patch_path = workspace / "patch.diff"

    command = [
        codex_bin,
        "exec",
        "--json",
        "--sandbox",
        "workspace-write",
        "-c",
        'approval_policy="never"',
        *extra_codex_args,
        prompt,
    ]
    if target.profile:
        command[2:2] = ["--profile", target.profile]
    for override in reversed(target.config_overrides):
        command[2:2] = ["-c", override]

    started = time.perf_counter()
    codex_exit_code = 1
    error: str | None = None
    env = None
    if target.env:
        import os

        env = os.environ.copy()
        env.update(target.env)
    try:
        codex_result = subprocess.run(
            command,
            cwd=workspace,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        codex_exit_code = codex_result.returncode
        codex_stdout.write_text(codex_result.stdout, encoding="utf-8")
        codex_stderr.write_text(codex_result.stderr, encoding="utf-8")
        if codex_result.returncode != 0:
            error = f"codex exited with {codex_result.returncode}"
    except subprocess.TimeoutExpired as exc:
        codex_stdout.write_text(_timeout_output(exc.stdout), encoding="utf-8")
        codex_stderr.write_text(_timeout_output(exc.stderr), encoding="utf-8")
        error = f"codex timed out after {timeout_seconds}s"
    codex_duration = time.perf_counter() - started

    verify_exit_code: int | None = None
    verify_duration: float | None = None
    if codex_exit_code == 0:
        verify_started = time.perf_counter()
        verify_result = subprocess.run(
            task.verify_command,
            cwd=workspace,
            shell=True,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        verify_duration = time.perf_counter() - verify_started
        verify_exit_code = verify_result.returncode
        verify_stdout.write_text(verify_result.stdout, encoding="utf-8")
        verify_stderr.write_text(verify_result.stderr, encoding="utf-8")
        if verify_result.returncode != 0 and error is None:
            error = f"verify exited with {verify_result.returncode}"
    else:
        verify_stdout.write_text("", encoding="utf-8")
        verify_stderr.write_text("verify skipped because codex failed\n", encoding="utf-8")

    usage = _extract_codex_usage(codex_stdout)
    estimated_cost = calculate_token_cost(usage, target.pricing)
    _write_patch(workspace, patch_path)
    changed_files = _changed_files(workspace)
    return CodexRunResult(
        task_id=task.id,
        target=target.name,
        profile=target.profile,
        repeat_index=repeat_index,
        workspace=str(workspace),
        codex_exit_code=codex_exit_code,
        verify_exit_code=verify_exit_code,
        passed=codex_exit_code == 0 and verify_exit_code == 0,
        codex_duration_seconds=round(codex_duration, 6),
        verify_duration_seconds=round(verify_duration, 6) if verify_duration is not None else None,
        patch_path=str(patch_path),
        changed_files=changed_files,
        error=error,
        usage=usage,
        estimated_cost=estimated_cost,
        currency=None if target.pricing is None else target.pricing.currency,
    )


def _ensure_git_baseline(workspace: Path) -> None:
    if (workspace / ".git").exists():
        return
    _run_git(["init"], workspace)
    _run_git(["add", "."], workspace)
    _run_git(
        [
            "-c",
            "user.name=llm-gateway-eval",
            "-c",
            "user.email=llm-gateway-eval@example.invalid",
            "commit",
            "-m",
            "baseline",
            "--allow-empty",
        ],
        workspace,
    )


def _exclude_runner_artifacts(workspace: Path) -> None:
    info_exclude = workspace / ".git" / "info" / "exclude"
    if not info_exclude.exists():
        return
    existing = info_exclude.read_text(encoding="utf-8")
    patterns = [
        "codex-events.jsonl",
        "codex-stderr.txt",
        "verify-stdout.txt",
        "verify-stderr.txt",
        "patch.diff",
    ]
    additions = [pattern for pattern in patterns if pattern not in existing]
    if additions:
        info_exclude.write_text(existing.rstrip() + "\n" + "\n".join(additions) + "\n", encoding="utf-8")


def _write_patch(workspace: Path, patch_path: Path) -> None:
    _run_git(["add", "-N", "."], workspace, check=False)
    result = _run_git(["diff", "--binary", "HEAD"], workspace, check=False)
    patch_path.write_text(result.stdout, encoding="utf-8")


def _changed_files(workspace: Path) -> list[str]:
    result = _run_git(["status", "--short"], workspace, check=False)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _run_git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=check,
    )


def _timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _extract_codex_usage(events_path: Path) -> dict[str, int]:
    if not events_path.exists():
        return {}

    total = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": 0,
    }
    found = False
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        usage = event.get("usage")
        if not isinstance(usage, dict):
            continue
        found = True
        input_tokens = _usage_int(usage, "input_tokens", "prompt_tokens")
        cached_input_tokens = _usage_int(usage, "cached_input_tokens")
        output_tokens = _usage_int(usage, "output_tokens", "completion_tokens")
        reasoning_output_tokens = _usage_int(usage, "reasoning_output_tokens")
        total_tokens = _usage_int(usage, "total_tokens")
        if total_tokens == 0:
            total_tokens = input_tokens + output_tokens
        total["input_tokens"] += input_tokens
        total["cached_input_tokens"] += cached_input_tokens
        total["output_tokens"] += output_tokens
        total["reasoning_output_tokens"] += reasoning_output_tokens
        total["total_tokens"] += total_tokens

    if not found:
        return {}
    return total


def _usage_int(usage: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = usage.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    return 0


def _summarize_group(results: list[CodexRunResult]) -> dict[str, Any]:
    codex_durations = [result.codex_duration_seconds for result in results]
    verify_durations = [
        result.verify_duration_seconds
        for result in results
        if result.verify_duration_seconds is not None
    ]
    costs = [result.estimated_cost for result in results if result.estimated_cost is not None]
    usage = _sum_usage(results)
    pass_count = sum(1 for result in results if result.passed)
    return {
        "runs": len(results),
        "passed": pass_count,
        "pass_rate": _rate(pass_count, len(results)),
        "codex_failures": sum(1 for result in results if result.codex_exit_code != 0),
        "verify_failures": sum(1 for result in results if result.codex_exit_code == 0 and result.verify_exit_code != 0),
        "avg_codex_duration_seconds": _avg(codex_durations),
        "avg_verify_duration_seconds": _avg(verify_durations),
        "usage": usage,
        "estimated_cost": round(sum(costs), 8) if costs else None,
        "currency": _first_currency(results),
        "cost_per_pass": round(sum(costs) / pass_count, 8) if costs and pass_count else None,
    }


def _paired_task_deltas(by_task: dict[str, list[CodexRunResult]]) -> list[dict[str, Any]]:
    deltas: list[dict[str, Any]] = []
    for task_id, results in sorted(by_task.items()):
        grouped: dict[str, list[CodexRunResult]] = defaultdict(list)
        for result in results:
            grouped[result.target].append(result)
        if len(grouped) < 2:
            continue
        target_rates = {
            target: _rate(sum(1 for item in items if item.passed), len(items))
            for target, items in sorted(grouped.items())
        }
        rates = list(target_rates.values())
        deltas.append(
            {
                "task_id": task_id,
                "target_pass_rates": target_rates,
                "max_delta": round(max(rates) - min(rates), 6),
            }
        )
    return deltas


def _sum_usage(results: list[CodexRunResult]) -> dict[str, int]:
    total = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": 0,
    }
    for result in results:
        for key in total:
            total[key] += result.usage.get(key, 0)
    return total


def _pricing_comparison(targets_summary: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    official = targets_summary.get("official")
    gateway = targets_summary.get("gateway")
    if not official or not gateway:
        return None
    official_cost = official.get("estimated_cost")
    gateway_cost = gateway.get("estimated_cost")
    if official_cost is None or gateway_cost is None:
        return None
    delta = gateway_cost - official_cost
    ratio = None if official_cost == 0 else gateway_cost / official_cost
    percent_delta = None if ratio is None else (ratio - 1) * 100
    return {
        "official_estimated_cost": round(official_cost, 8),
        "gateway_estimated_cost": round(gateway_cost, 8),
        "absolute_delta": round(delta, 8),
        "percent_delta": None if percent_delta is None else round(percent_delta, 2),
        "gateway_to_official_ratio": None if ratio is None else round(ratio, 4),
        "currency": gateway.get("currency") or official.get("currency"),
    }


def _first_currency(results: list[CodexRunResult]) -> str | None:
    for result in results:
        if result.currency:
            return result.currency
    return None


def _rate(numerator: int, denominator: int) -> float:
    return 0.0 if denominator == 0 else round(numerator / denominator, 6)


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)
