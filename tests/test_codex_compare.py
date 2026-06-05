import json
from pathlib import Path

from typer.testing import CliRunner

from llm_gateway_eval.cli import app
from llm_gateway_eval.codex_compare import (
    CodexCompareTarget,
    discover_tasks,
    run_codex_compare,
    write_codex_compare_outputs,
)
from llm_gateway_eval.codex_report import render_codex_compare_report


def test_codex_compare_detects_gateway_delta(tmp_path) -> None:
    fake_codex = _write_fake_codex(tmp_path)
    project_root = Path(__file__).resolve().parents[1]
    tasks = discover_tasks(project_root / "data" / "codex_tasks")
    targets = [
        CodexCompareTarget(name="official", profile="official-good"),
        CodexCompareTarget(name="gateway", profile="gateway-bad"),
    ]

    results, summary = run_codex_compare(
        tasks=tasks,
        targets=targets,
        repeats=1,
        out_dir=tmp_path / "run",
        codex_bin=str(fake_codex),
        timeout_seconds=30,
    )
    results_path, summary_path = write_codex_compare_outputs(results, summary, tmp_path / "run")
    report_path = render_codex_compare_report(tmp_path / "run", tmp_path / "report.md")

    assert results_path.exists()
    assert summary_path.exists()
    assert report_path.exists()
    assert summary["targets_summary"]["official"]["pass_rate"] == 1.0
    assert summary["targets_summary"]["gateway"]["pass_rate"] == 0.0
    assert summary["paired_task_deltas"][0]["max_delta"] == 1.0
    assert "Codex Official vs Gateway Comparison" in report_path.read_text(encoding="utf-8")


def test_codex_quick_compare_uses_url_and_key_without_profiles(tmp_path) -> None:
    fake_codex = _write_fake_codex(tmp_path)
    project_root = Path(__file__).resolve().parents[1]
    run_dir = tmp_path / "quick-run"
    report_path = tmp_path / "quick-report.md"

    result = CliRunner().invoke(
        app,
        [
            "codex-quick-compare",
            "--gateway-url",
            "https://gateway.example.com/v1",
            "--gateway-api-key",
            "sk-test-not-written-to-summary",
            "--model",
            "gpt-5.4-mini",
            "--gateway-price-multiplier",
            "2",
            "--tasks",
            str(project_root / "data" / "codex_tasks"),
            "--repeats",
            "1",
            "--codex-bin",
            str(fake_codex),
            "--out",
            str(run_dir),
            "--report-out",
            str(report_path),
        ],
    )

    assert result.exit_code == 0, result.output
    summary_text = (run_dir / "summary.json").read_text(encoding="utf-8")
    summary = json.loads(summary_text)
    assert "sk-test-not-written-to-summary" not in summary_text
    assert summary["gateway_url"] == "https://gateway.example.com/v1"
    assert summary["targets_summary"]["official"]["pass_rate"] == 1.0
    assert summary["targets_summary"]["gateway"]["pass_rate"] == 0.0
    assert summary["pricing_comparison"]["gateway_to_official_ratio"] == 2
    assert report_path.exists()


def test_codex_quick_compare_auto_fetches_weytoken_price(tmp_path, monkeypatch) -> None:
    fake_codex = _write_fake_codex(tmp_path)
    project_root = Path(__file__).resolve().parents[1]
    run_dir = tmp_path / "weytoken-run"
    report_path = tmp_path / "weytoken-report.md"

    def fake_price_for_model(base_url: str, model: str, group: str, currency: str):
        assert base_url == "https://api.weytoken.com/v1"
        assert model == "gpt-5.4-mini"
        assert group == "best"
        assert currency == "USD"
        from llm_gateway_eval.pricing import TokenPricing

        return TokenPricing(input_per_million=1.5, cached_input_per_million=0.15, output_per_million=9.0)

    monkeypatch.setattr("llm_gateway_eval.cli.price_for_model", fake_price_for_model)
    result = CliRunner().invoke(
        app,
        [
            "codex-quick-compare",
            "--gateway-url",
            "https://api.weytoken.com/v1",
            "--gateway-api-key",
            "sk-test-not-written-to-summary",
            "--model",
            "gpt-5.4-mini",
            "--tasks",
            str(project_root / "data" / "codex_tasks"),
            "--repeats",
            "1",
            "--codex-bin",
            str(fake_codex),
            "--out",
            str(run_dir),
            "--report-out",
            str(report_path),
        ],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["pricing_comparison"]["gateway_to_official_ratio"] == 2


def _write_fake_codex(tmp_path: Path) -> Path:
    script = tmp_path / "fake-codex"
    script.write_text(
        """#!/usr/bin/env python3
import json
import pathlib
import sys


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
            "    tag_counts = {}\\n"
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
            "    return {'active_count': active_count, 'emails': sorted(emails), 'tag_counts': tag_counts}\\n",
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
            "    seen = {}\\n"
            "    in_fence = False\\n"
            "    for line in markdown.splitlines():\\n"
            "        if line.strip().startswith('```'):\\n"
            "            in_fence = not in_fence\\n"
            "            continue\\n"
            "        if in_fence:\\n"
            "            continue\\n"
            "        match = re.match(r'^(#{1,6})\\\\s+(.+?)\\\\s*$', line)\\n"
            "        if not match:\\n"
            "            continue\\n"
            "        title = match.group(2).strip()\\n"
            "        base = _slugify(title)\\n"
            "        seen[base] = seen.get(base, 0) + 1\\n"
            "        slug = base if seen[base] == 1 else f'{base}-{seen[base]}'\\n"
            "        items.append({'level': len(match.group(1)), 'title': title, 'slug': slug})\\n"
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
            "    return {'subtotal': _format_money(subtotal), 'tax': _format_money(tax_amount), 'total': _format_money(total)}\\n",
            encoding="utf-8",
        )


profile = sys.argv[sys.argv.index("--profile") + 1] if "--profile" in sys.argv else None
is_gateway = any("model_provider" in arg and "gateway" in arg for arg in sys.argv)
if profile == "official-good" or (profile is None and not is_gateway):
    fix_current_workspace()
print(json.dumps({
    "type": "turn.completed",
    "profile": profile,
    "usage": {
        "input_tokens": 1000,
        "cached_input_tokens": 100,
        "output_tokens": 200,
        "reasoning_output_tokens": 50,
        "total_tokens": 1200
    }
}))
""",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | 0o111)
    return script
