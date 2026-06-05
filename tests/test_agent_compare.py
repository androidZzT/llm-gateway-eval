import json
import os
from pathlib import Path

from typer.testing import CliRunner

from llm_gateway_eval.cli import app


def test_agent_compare_runs_codex_and_claude_code_targets(tmp_path) -> None:
    fake_codex = _write_fake_agent(tmp_path, "fake-codex", fixes_code=True, usage_shape="codex")
    fake_claude = _write_fake_agent(tmp_path, "fake-claude", fixes_code=False, usage_shape="claude")
    project_root = Path(__file__).resolve().parents[1]
    run_dir = tmp_path / "agent-run"
    report_path = tmp_path / "agent-report.md"

    result = CliRunner().invoke(
        app,
        [
            "agent-compare",
            "--tasks",
            str(project_root / "data" / "codex_tasks"),
            "--codex-bin",
            str(fake_codex),
            "--claude-bin",
            str(fake_claude),
            "--repeats",
            "1",
            "--out",
            str(run_dir),
            "--report-out",
            str(report_path),
        ],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["targets_summary"]["codex"]["pass_rate"] == 1.0
    assert summary["targets_summary"]["claude-code"]["pass_rate"] == 0.0
    assert summary["targets_summary"]["codex"]["usage"]["input_tokens"] == 5000
    assert summary["targets_summary"]["claude-code"]["usage"]["cached_input_tokens"] == 125
    assert summary["paired_task_deltas"][0]["max_delta"] == 1.0
    assert "Coding Agent Comparison" in report_path.read_text(encoding="utf-8")


def test_agent_compare_routes_claude_code_through_gateway_env(tmp_path, monkeypatch) -> None:
    fake_claude = _write_fake_agent(
        tmp_path,
        "fake-claude-gateway",
        fixes_code=True,
        usage_shape="claude",
        required_env={
            "ANTHROPIC_BASE_URL": "https://gateway.example.com",
            "ANTHROPIC_AUTH_TOKEN": "sk-claude-gateway-secret",
            "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1",
        },
    )
    project_root = Path(__file__).resolve().parents[1]
    run_dir = tmp_path / "agent-run"
    report_path = tmp_path / "agent-report.md"
    monkeypatch.delenv("LLM_GATEWAY_EVAL_CLAUDE_GATEWAY_API_KEY", raising=False)

    result = CliRunner().invoke(
        app,
        [
            "agent-compare",
            "--no-codex",
            "--tasks",
            str(project_root / "data" / "codex_tasks"),
            "--claude-bin",
            str(fake_claude),
            "--claude-gateway-url",
            "https://gateway.example.com",
            "--claude-gateway-api-key",
            "sk-claude-gateway-secret",
            "--claude-gateway-model-discovery",
            "--repeats",
            "1",
            "--out",
            str(run_dir),
            "--report-out",
            str(report_path),
        ],
    )

    assert result.exit_code == 0, result.output
    summary_text = (run_dir / "summary.json").read_text(encoding="utf-8")
    summary = json.loads(summary_text)
    assert summary["targets_summary"]["claude-code"]["pass_rate"] == 1.0
    assert summary["claude_gateway"]["url"] == "https://gateway.example.com"
    assert summary["targets"][0]["env_keys"] == [
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY",
    ]
    assert "sk-claude-gateway-secret" not in summary_text
    assert "sk-claude-gateway-secret" not in report_path.read_text(encoding="utf-8")
    assert "LLM_GATEWAY_EVAL_CLAUDE_GATEWAY_API_KEY" not in os.environ


def test_agent_compare_wraps_agent_with_cctrace(tmp_path) -> None:
    fake_codex = _write_fake_agent(tmp_path, "fake-codex", fixes_code=True, usage_shape="codex")
    fake_cctrace = _write_fake_cctrace(tmp_path)
    project_root = Path(__file__).resolve().parents[1]
    run_dir = tmp_path / "agent-run"
    report_path = tmp_path / "agent-report.md"

    result = CliRunner().invoke(
        app,
        [
            "agent-compare",
            "--no-claude",
            "--cctrace",
            "--cctrace-bin",
            str(fake_cctrace),
            "--tasks",
            str(project_root / "data" / "codex_tasks"),
            "--codex-bin",
            str(fake_codex),
            "--repeats",
            "1",
            "--out",
            str(run_dir),
            "--report-out",
            str(report_path),
        ],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["cctrace"]["enabled"] is True
    assert summary["cctrace"]["captured_runs"] == 5
    rows = (run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()
    row = json.loads(rows[0])
    assert row["cctrace_session_id"] == "sess_fake"
    assert row["cctrace_event_count"] == 2
    assert Path(row["cctrace_events_path"]).exists()
    assert "cctrace Evidence" in report_path.read_text(encoding="utf-8")


def _write_fake_agent(
    tmp_path: Path,
    name: str,
    fixes_code: bool,
    usage_shape: str,
    required_env: dict[str, str] | None = None,
) -> Path:
    script = tmp_path / name
    code_fix = "fix_current_workspace()"
    if usage_shape == "codex":
        usage = {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 1000,
                "cached_input_tokens": 100,
                "output_tokens": 200,
                "reasoning_output_tokens": 50,
                "total_tokens": 1200,
            },
        }
    else:
        usage = {
            "type": "assistant",
            "message": {
                "usage": {
                    "input_tokens": 500,
                    "cache_read_input_tokens": 25,
                    "output_tokens": 80,
                }
            },
        }
    env_check = "True"
    if required_env:
        env_check = " and ".join(
            f"os.environ.get({key!r}) == {value!r}"
            for key, value in required_env.items()
        )
    script.write_text(
        f"""#!/usr/bin/env python3
import json
import os
import pathlib


def fix_current_workspace() -> None:
    if pathlib.Path("palindrome.py").exists():
        pathlib.Path("palindrome.py").write_text(
            "def is_palindrome(value: str) -> bool:\\n"
            "    normalized = ''.join(ch.lower() for ch in value if ch.isalnum())\\n"
            "    return normalized == normalized[::-1]\\n",
            encoding="utf-8",
        )
    if pathlib.Path("events.py").exists():
        pathlib.Path("events.py").write_text(
            "import json\\n\\n"
            "def summarize_events(raw: str) -> dict:\\n"
            "    active_count = 0\\n"
            "    emails = set()\\n"
            "    tag_counts = {{}}\\n"
            "    for line in raw.splitlines():\\n"
            "        line = line.strip()\\n"
            "        if not line:\\n"
            "            continue\\n"
            "        try:\\n"
            "            record = json.loads(line)\\n"
            "        except json.JSONDecodeError:\\n"
            "            continue\\n"
            "        if not record.get('active'):\\n"
            "            continue\\n"
            "        active_count += 1\\n"
            "        email = str(record.get('email', '')).lower()\\n"
            "        if email:\\n"
            "            emails.add(email)\\n"
            "        for tag in record.get('tags') or []:\\n"
            "            tag_counts[tag] = tag_counts.get(tag, 0) + 1\\n"
            "    return {{'active_count': active_count, 'emails': sorted(emails), 'tag_counts': tag_counts}}\\n",
            encoding="utf-8",
        )
    if pathlib.Path("toc.py").exists():
        pathlib.Path("toc.py").write_text(
            "import re\\n\\n"
            "def _slugify(title: str) -> str:\\n"
            "    text = re.sub(r'[^\\\\w\\\\s-]', '', title.lower())\\n"
            "    return re.sub(r'[_\\\\s-]+', '-', text).strip('-')\\n\\n"
            "def build_toc(markdown: str) -> list[dict]:\\n"
            "    items = []\\n"
            "    seen = {{}}\\n"
            "    in_fence = False\\n"
            "    for line in markdown.splitlines():\\n"
            "        if line.strip().startswith('```'):\\n"
            "            in_fence = not in_fence\\n"
            "            continue\\n"
            "        if in_fence:\\n"
            "            continue\\n"
            "        match = re.match(r'^(#{{1,6}})\\\\s+(.+?)\\\\s*$', line)\\n"
            "        if not match:\\n"
            "            continue\\n"
            "        title = match.group(2).strip()\\n"
            "        base = _slugify(title)\\n"
            "        seen[base] = seen.get(base, 0) + 1\\n"
            "        slug = base if seen[base] == 1 else f'{{base}}-{{seen[base]}}'\\n"
            "        items.append({{'level': len(match.group(1)), 'title': title, 'slug': slug}})\\n"
            "    return items\\n",
            encoding="utf-8",
        )
    if pathlib.Path("retry.py").exists():
        pathlib.Path("retry.py").write_text(
            "def retry_delays(attempts: int, base: float = 0.5, cap: float = 8.0, jitter: float = 0.0) -> list[float]:\\n"
            "    offsets = (-jitter, 0.0, jitter)\\n"
            "    delays = []\\n"
            "    for index in range(attempts):\\n"
            "        value = min(cap, base * (2 ** index)) + offsets[index % len(offsets)]\\n"
            "        value = max(0.0, min(cap, value))\\n"
            "        delays.append(round(value, 10))\\n"
            "    return delays\\n",
            encoding="utf-8",
        )
    if pathlib.Path("invoice.py").exists():
        pathlib.Path("invoice.py").write_text(
            "from decimal import Decimal, ROUND_HALF_UP\\n\\n"
            "MONEY = Decimal('0.01')\\n\\n"
            "def _decimal(value) -> Decimal:\\n"
            "    return Decimal(str(value))\\n\\n"
            "def _format_money(value: Decimal) -> str:\\n"
            "    return str(value.quantize(MONEY, rounding=ROUND_HALF_UP))\\n\\n"
            "def calculate_invoice(items: list[dict], tax_rate: str = '0') -> dict[str, str]:\\n"
            "    tax = _decimal(tax_rate)\\n"
            "    if tax < 0:\\n"
            "        raise ValueError('tax_rate cannot be negative')\\n"
            "    subtotal = Decimal('0')\\n"
            "    for item in items:\\n"
            "        quantity = _decimal(item.get('quantity', 0))\\n"
            "        unit_price = _decimal(item.get('unit_price', 0))\\n"
            "        discount = _decimal(item.get('discount_percent', 0))\\n"
            "        if quantity < 0 or unit_price < 0 or discount < 0:\\n"
            "            raise ValueError('invoice values cannot be negative')\\n"
            "        subtotal += quantity * unit_price * (Decimal('1') - discount / Decimal('100'))\\n"
            "    subtotal = subtotal.quantize(MONEY, rounding=ROUND_HALF_UP)\\n"
            "    tax_amount = (subtotal * tax).quantize(MONEY, rounding=ROUND_HALF_UP)\\n"
            "    total = subtotal + tax_amount\\n"
            "    return {{'subtotal': _format_money(subtotal), 'tax': _format_money(tax_amount), 'total': _format_money(total)}}\\n",
            encoding="utf-8",
        )


if {fixes_code!r} and ({env_check}):
    {code_fix}
print(json.dumps({usage!r}))
""",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | 0o111)
    return script


def _write_fake_cctrace(tmp_path: Path) -> Path:
    script = tmp_path / "fake-cctrace"
    script.write_text(
        """#!/usr/bin/env python3
import json
import os
import pathlib
import subprocess
import sys

separator = sys.argv.index("--")
provider = sys.argv[1]
command = sys.argv[separator + 1:]
store = pathlib.Path(os.environ["TMPDIR"]) / "cctrace-sessions" / "sess_fake"
store.mkdir(parents=True, exist_ok=True)
(store / "session.json").write_text(json.dumps({"id": "sess_fake", "command": command}), encoding="utf-8")
events = [
    {"id": "evt_start", "sessionId": "sess_fake", "type": "process", "title": provider + " started"},
    {"id": "evt_exit", "sessionId": "sess_fake", "type": "process", "title": provider + " exited"},
]
(store / "events.jsonl").write_text("\\n".join(json.dumps(event) for event in events) + "\\n", encoding="utf-8")
result = subprocess.run(command, text=True, capture_output=True)
sys.stdout.write(result.stdout)
sys.stderr.write(result.stderr)
raise SystemExit(result.returncode)
""",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | 0o111)
    return script
