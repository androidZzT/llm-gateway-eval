from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import AssertionSpec, EvalCase


class CaseError(ValueError):
    pass


def load_cases(path: str | Path) -> list[EvalCase]:
    cases_path = Path(path)
    cases: list[EvalCase] = []
    seen_ids: set[str] = set()

    for line_number, line in enumerate(cases_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CaseError(f"{cases_path}:{line_number} is not valid JSON: {exc}") from exc
        case = _parse_case(raw, cases_path, line_number)
        if case.id in seen_ids:
            raise CaseError(f"{cases_path}:{line_number} duplicates case id {case.id!r}")
        seen_ids.add(case.id)
        cases.append(case)

    if not cases:
        raise CaseError(f"No eval cases found in {cases_path}")
    return cases


def _parse_case(raw: Any, path: Path, line_number: int) -> EvalCase:
    if not isinstance(raw, dict):
        raise CaseError(f"{path}:{line_number} must be a JSON object.")

    missing = [key for key in ("id", "category", "messages") if key not in raw]
    if missing:
        raise CaseError(f"{path}:{line_number} missing required field(s): {', '.join(missing)}")

    messages = raw["messages"]
    if not isinstance(messages, list) or not messages:
        raise CaseError(f"{path}:{line_number} messages must be a non-empty list.")
    for message in messages:
        if not isinstance(message, dict) or "role" not in message or "content" not in message:
            raise CaseError(f"{path}:{line_number} each message must include role and content.")

    assertions = raw.get("assertions", [])
    if not isinstance(assertions, list):
        raise CaseError(f"{path}:{line_number} assertions must be a list.")

    tags = raw.get("tags", [])
    if not isinstance(tags, list):
        raise CaseError(f"{path}:{line_number} tags must be a list.")

    return EvalCase(
        id=str(raw["id"]),
        category=str(raw["category"]),
        messages=messages,
        expected=raw.get("expected"),
        assertions=[_parse_assertion(item, path, line_number) for item in assertions],
        tags=[str(tag) for tag in tags],
    )


def _parse_assertion(raw: Any, path: Path, line_number: int) -> AssertionSpec:
    if not isinstance(raw, dict) or "type" not in raw:
        raise CaseError(f"{path}:{line_number} each assertion must include type.")
    return AssertionSpec(
        type=str(raw["type"]),
        value=raw.get("value"),
        schema=raw.get("schema"),
        flags=raw.get("flags"),
    )

