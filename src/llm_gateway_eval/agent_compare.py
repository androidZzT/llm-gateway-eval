from __future__ import annotations

import json
import os
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
class AgentCompareTarget:
    name: str
    agent: str
    command: list[str]
    env: dict[str, str] = field(default_factory=dict)
    pricing: TokenPricing | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "agent": self.agent,
            "command": _redact_command(self.command),
            "env_keys": sorted(self.env),
            "pricing": None if self.pricing is None else self.pricing.to_dict(),
        }


@dataclass(frozen=True)
class AgentTask:
    id: str
    path: Path
    repo_path: Path
    prompt_path: Path
    verify_command: str


@dataclass(frozen=True)
class AgentRunResult:
    task_id: str
    target: str
    agent: str
    repeat_index: int
    workspace: str
    agent_exit_code: int
    verify_exit_code: int | None
    passed: bool
    agent_duration_seconds: float
    verify_duration_seconds: float | None
    stdout_path: str
    stderr_path: str
    patch_path: str
    changed_files: list[str]
    error: str | None
    usage: dict[str, int]
    estimated_cost: float | None
    currency: str | None
    cctrace_enabled: bool = False
    cctrace_session_id: str | None = None
    cctrace_session_path: str | None = None
    cctrace_events_path: str | None = None
    cctrace_event_count: int | None = None
    cctrace_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AgentCompareError(ValueError):
    pass


def discover_agent_tasks(
    tasks_dir: str | Path,
    prompt_file: str = "TASK.md",
    verify_command: str = "bash ./verify.sh",
) -> list[AgentTask]:
    root = Path(tasks_dir)
    if not root.exists():
        raise AgentCompareError(f"Tasks directory does not exist: {root}")

    tasks: list[AgentTask] = []
    for task_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        repo_path = task_dir / "repo"
        prompt_path = task_dir / prompt_file
        if not repo_path.is_dir() or not prompt_path.is_file():
            continue
        tasks.append(
            AgentTask(
                id=task_dir.name,
                path=task_dir,
                repo_path=repo_path,
                prompt_path=prompt_path,
                verify_command=verify_command,
            )
        )

    if not tasks:
        raise AgentCompareError(
            f"No tasks found in {root}. Expected subdirectories containing repo/ and {prompt_file}."
        )
    return tasks


def run_agent_compare(
    tasks: list[AgentTask],
    targets: list[AgentCompareTarget],
    repeats: int,
    out_dir: str | Path,
    timeout_seconds: int = 1800,
    cctrace_enabled: bool = False,
    cctrace_bin: str = "cctrace",
) -> tuple[list[AgentRunResult], dict[str, Any]]:
    output_root = Path(out_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    results: list[AgentRunResult] = []

    for target in targets:
        for task in tasks:
            for repeat_index in range(1, repeats + 1):
                results.append(
                    _run_single(
                        task=task,
                        target=target,
                        repeat_index=repeat_index,
                        output_root=output_root,
                        timeout_seconds=timeout_seconds,
                        cctrace_enabled=cctrace_enabled,
                        cctrace_bin=cctrace_bin,
                    )
                )

    summary = summarize_agent_results(results)
    summary["generated_at"] = datetime.now(timezone.utc).isoformat()
    summary["task_count"] = len(tasks)
    summary["targets"] = [target.public_dict() for target in targets]
    summary["repeats"] = repeats
    summary["cctrace"] = {
        "enabled": cctrace_enabled,
        "bin": cctrace_bin if cctrace_enabled else None,
        "captured_runs": sum(1 for result in results if result.cctrace_session_path),
        "failed_runs": sum(1 for result in results if result.cctrace_enabled and not result.cctrace_session_path),
    }
    return results, summary


def write_agent_compare_outputs(
    results: list[AgentRunResult],
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


def summarize_agent_results(results: list[AgentRunResult]) -> dict[str, Any]:
    by_target: dict[str, list[AgentRunResult]] = defaultdict(list)
    by_task: dict[str, list[AgentRunResult]] = defaultdict(list)
    for result in results:
        by_target[result.target].append(result)
        by_task[result.task_id].append(result)

    targets_summary = {
        target: _summarize_group(items)
        for target, items in sorted(by_target.items())
    }
    return {
        "title": "Coding Agent Comparison",
        "total_runs": len(results),
        "overall_pass_rate": _rate(sum(1 for result in results if result.passed), len(results)),
        "targets_summary": targets_summary,
        "tasks_summary": {
            task_id: _summarize_group(items)
            for task_id, items in sorted(by_task.items())
        },
        "paired_task_deltas": _paired_task_deltas(by_task),
    }


def build_codex_agent_target(
    name: str = "codex",
    codex_bin: str = "codex",
    model: str | None = None,
    profile: str | None = None,
    pricing: TokenPricing | None = None,
    extra_args: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> AgentCompareTarget:
    command = [
        codex_bin,
        "exec",
        "--json",
        "--sandbox",
        "workspace-write",
        "-c",
        'approval_policy="never"',
        "-c",
        'web_search="disabled"',
    ]
    if profile:
        command.extend(["--profile", profile])
    if model:
        command.extend(["--model", model])
    command.extend(extra_args or [])
    command.append("{prompt}")
    return AgentCompareTarget(name=name, agent="codex", command=command, env=env or {}, pricing=pricing)


def build_claude_agent_target(
    name: str = "claude-code",
    claude_bin: str = "claude",
    model: str | None = None,
    permission_mode: str = "bypassPermissions",
    output_format: str = "stream-json",
    pricing: TokenPricing | None = None,
    extra_args: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> AgentCompareTarget:
    command = [
        claude_bin,
        "--print",
        "--permission-mode",
        permission_mode,
        "--output-format",
        output_format,
        "--no-session-persistence",
    ]
    if model:
        command.extend(["--model", model])
    command.extend(extra_args or [])
    command.append("{prompt}")
    return AgentCompareTarget(name=name, agent="claude-code", command=command, env=env or {}, pricing=pricing)


def _run_single(
    task: AgentTask,
    target: AgentCompareTarget,
    repeat_index: int,
    output_root: Path,
    timeout_seconds: int,
    cctrace_enabled: bool,
    cctrace_bin: str,
) -> AgentRunResult:
    workspace = output_root / "workspaces" / target.name / task.id / f"run-{repeat_index}"
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(task.repo_path, workspace)
    _ensure_git_baseline(workspace)
    _exclude_runner_artifacts(workspace)

    prompt = task.prompt_path.read_text(encoding="utf-8")
    stdout_path = workspace / "agent-stdout.jsonl"
    stderr_path = workspace / "agent-stderr.txt"
    verify_stdout = workspace / "verify-stdout.txt"
    verify_stderr = workspace / "verify-stderr.txt"
    patch_path = workspace / "patch.diff"

    command = _render_command(target.command, prompt=prompt, task=task, workspace=workspace)
    cctrace: dict[str, Any] = {
        "enabled": cctrace_enabled,
        "session_id": None,
        "session_path": None,
        "events_path": None,
        "event_count": None,
        "error": None,
    }
    started = time.perf_counter()
    agent_exit_code = 1
    error: str | None = None
    env = os.environ.copy()
    env.update(target.env)
    run_command = command
    if cctrace_enabled:
        cctrace_tmp = workspace / ".cctrace-tmp"
        cctrace_tmp.mkdir(parents=True, exist_ok=True)
        env["TMPDIR"] = str(cctrace_tmp)
        provider = _cctrace_provider(target.agent)
        if provider is None:
            cctrace["error"] = f"unsupported cctrace provider for agent {target.agent}"
        else:
            run_command = [cctrace_bin, provider, "--", *command]
    try:
        agent_result = subprocess.run(
            run_command,
            cwd=workspace,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        agent_exit_code = agent_result.returncode
        stdout_path.write_text(agent_result.stdout, encoding="utf-8")
        stderr_path.write_text(agent_result.stderr, encoding="utf-8")
        if agent_result.returncode != 0:
            error = f"{target.agent} exited with {agent_result.returncode}"
    except subprocess.TimeoutExpired as exc:
        stdout_path.write_text(_timeout_output(exc.stdout), encoding="utf-8")
        stderr_path.write_text(_timeout_output(exc.stderr), encoding="utf-8")
        error = f"{target.agent} timed out after {timeout_seconds}s"
    agent_duration = time.perf_counter() - started
    if cctrace_enabled:
        cctrace.update(_collect_cctrace_artifacts(workspace))

    verify_exit_code: int | None = None
    verify_duration: float | None = None
    if agent_exit_code == 0:
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
        verify_stderr.write_text(f"verify skipped because {target.agent} failed\n", encoding="utf-8")

    usage = _extract_usage(stdout_path)
    estimated_cost = calculate_token_cost(usage, target.pricing)
    _write_patch(workspace, patch_path)
    changed_files = _changed_files(workspace)
    return AgentRunResult(
        task_id=task.id,
        target=target.name,
        agent=target.agent,
        repeat_index=repeat_index,
        workspace=str(workspace),
        agent_exit_code=agent_exit_code,
        verify_exit_code=verify_exit_code,
        passed=agent_exit_code == 0 and verify_exit_code == 0,
        agent_duration_seconds=round(agent_duration, 6),
        verify_duration_seconds=round(verify_duration, 6) if verify_duration is not None else None,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        patch_path=str(patch_path),
        changed_files=changed_files,
        error=error,
        usage=usage,
        estimated_cost=estimated_cost,
        currency=None if target.pricing is None else target.pricing.currency,
        cctrace_enabled=bool(cctrace["enabled"]),
        cctrace_session_id=cctrace["session_id"],
        cctrace_session_path=cctrace["session_path"],
        cctrace_events_path=cctrace["events_path"],
        cctrace_event_count=cctrace["event_count"],
        cctrace_error=cctrace["error"],
    )


def _render_command(command: list[str], prompt: str, task: AgentTask, workspace: Path) -> list[str]:
    replacements = {
        "{prompt}": prompt,
        "{prompt_file}": str(task.prompt_path),
        "{task_id}": task.id,
        "{workspace}": str(workspace),
    }
    return [replacements.get(part, part) for part in command]


def _extract_usage(events_path: Path) -> dict[str, int]:
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
        for usage in _iter_usage_dicts(event):
            found = True
            input_tokens = _usage_int(usage, "input_tokens", "prompt_tokens")
            cached_input_tokens = _usage_int(
                usage,
                "cached_input_tokens",
                "cache_read_input_tokens",
                "cache_creation_input_tokens",
            )
            output_tokens = _usage_int(usage, "output_tokens", "completion_tokens")
            reasoning_output_tokens = _usage_int(usage, "reasoning_output_tokens")
            total_tokens = _usage_int(usage, "total_tokens")
            if total_tokens == 0:
                total_tokens = input_tokens + cached_input_tokens + output_tokens
            total["input_tokens"] += input_tokens
            total["cached_input_tokens"] += cached_input_tokens
            total["output_tokens"] += output_tokens
            total["reasoning_output_tokens"] += reasoning_output_tokens
            total["total_tokens"] += total_tokens

    if not found:
        return {}
    return total


def _iter_usage_dicts(value: Any):
    if isinstance(value, dict):
        usage = value.get("usage")
        if isinstance(usage, dict):
            yield usage
        for item in value.values():
            yield from _iter_usage_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_usage_dicts(item)


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


def _summarize_group(results: list[AgentRunResult]) -> dict[str, Any]:
    agent_durations = [result.agent_duration_seconds for result in results]
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
        "agent_failures": sum(1 for result in results if result.agent_exit_code != 0),
        "verify_failures": sum(1 for result in results if result.agent_exit_code == 0 and result.verify_exit_code != 0),
        "avg_agent_duration_seconds": _avg(agent_durations),
        "avg_verify_duration_seconds": _avg(verify_durations),
        "usage": usage,
        "estimated_cost": round(sum(costs), 8) if costs else None,
        "currency": _first_currency(results),
        "cost_per_pass": round(sum(costs) / pass_count, 8) if costs and pass_count else None,
    }


def _paired_task_deltas(by_task: dict[str, list[AgentRunResult]]) -> list[dict[str, Any]]:
    deltas: list[dict[str, Any]] = []
    for task_id, results in sorted(by_task.items()):
        grouped: dict[str, list[AgentRunResult]] = defaultdict(list)
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


def _sum_usage(results: list[AgentRunResult]) -> dict[str, int]:
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
        "agent-stdout.jsonl",
        "agent-stderr.txt",
        "verify-stdout.txt",
        "verify-stderr.txt",
        "patch.diff",
        ".cctrace-tmp/",
        "cctrace-session/",
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


def _cctrace_provider(agent: str) -> str | None:
    if agent == "codex":
        return "codex"
    if agent == "claude-code":
        return "claude"
    return None


def _collect_cctrace_artifacts(workspace: Path) -> dict[str, Any]:
    store_dir = workspace / ".cctrace-tmp" / "cctrace-sessions"
    if not store_dir.exists():
        return {
            "session_id": None,
            "session_path": None,
            "events_path": None,
            "event_count": None,
            "error": f"cctrace store not found: {store_dir}",
        }

    session_dirs = [path for path in store_dir.iterdir() if path.is_dir()]
    if not session_dirs:
        return {
            "session_id": None,
            "session_path": None,
            "events_path": None,
            "event_count": None,
            "error": f"no cctrace session directories found in {store_dir}",
        }

    session_dir = max(session_dirs, key=lambda path: path.stat().st_mtime)
    stable_dir = workspace / "cctrace-session"
    if stable_dir.exists():
        shutil.rmtree(stable_dir)
    shutil.copytree(session_dir, stable_dir)
    events_path = stable_dir / "events.jsonl"
    event_count = _count_jsonl_lines(events_path)
    return {
        "session_id": session_dir.name,
        "session_path": str(stable_dir),
        "events_path": str(events_path) if events_path.exists() else None,
        "event_count": event_count,
        "error": None if events_path.exists() else f"cctrace events file not found: {events_path}",
    }


def _count_jsonl_lines(path: Path) -> int | None:
    if not path.exists():
        return None
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


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


def _first_currency(results: list[AgentRunResult]) -> str | None:
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


def _redact_command(command: list[str]) -> list[str]:
    redacted: list[str] = []
    for part in command:
        lowered = part.lower()
        if "api_key" in lowered or "api-key" in lowered or part.startswith("sk-"):
            redacted.append("[REDACTED]")
        else:
            redacted.append(part)
    return redacted
