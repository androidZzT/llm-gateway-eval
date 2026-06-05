from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .redaction import redact_text


def render_report(run_dir: str | Path, output_path: str | Path, template_path: str | Path | None = None) -> Path:
    run_path = Path(run_dir)
    summary = _load_json(run_path / "summary.json")
    results = _load_jsonl(run_path / "results.jsonl")
    failures = [_redact_result(result) for result in results if result.get("error") or not result.get("passed", False)][:20]

    template = _load_template(template_path)
    rendered = template.render(summary=summary, results=results, failures=failures)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered, encoding="utf-8")
    return out


def _load_template(template_path: str | Path | None):
    if template_path is not None:
        template_file = Path(template_path)
        env = Environment(
            loader=FileSystemLoader(str(template_file.parent)),
            autoescape=select_autoescape(enabled_extensions=()),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        return env.get_template(template_file.name)

    project_root = Path(__file__).resolve().parents[2]
    env = Environment(
        loader=FileSystemLoader(str(project_root / "templates")),
        autoescape=select_autoescape(enabled_extensions=()),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env.get_template("report.md.j2")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _redact_result(result: dict[str, Any]) -> dict[str, Any]:
    copied = dict(result)
    copied["output"] = redact_text(copied.get("output", ""))
    if copied.get("error"):
        copied["error"] = redact_text(copied["error"])
    return copied
