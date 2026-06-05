from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape


def render_codex_compare_report(run_dir: str | Path, output_path: str | Path) -> Path:
    run_path = Path(run_dir)
    summary = _load_json(run_path / "summary.json")
    results = _load_jsonl(run_path / "results.jsonl")
    failures = [result for result in results if not result.get("passed")][:20]

    project_root = Path(__file__).resolve().parents[2]
    env = Environment(
        loader=FileSystemLoader(str(project_root / "templates")),
        autoescape=select_autoescape(enabled_extensions=()),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    rendered = env.get_template("codex_compare_report.md.j2").render(
        summary=summary,
        results=results,
        failures=failures,
    )

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered, encoding="utf-8")
    return out


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

