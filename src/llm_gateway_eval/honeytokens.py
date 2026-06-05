from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .redaction import redact_text


@dataclass(frozen=True)
class HoneytokenEventAnalysis:
    source_path: str
    checked_at: str
    token_count: int
    total_records: int
    matched_event_count: int
    matches: list[dict[str, Any]]
    status: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "checked_at": self.checked_at,
            "token_count": self.token_count,
            "total_records": self.total_records,
            "matched_event_count": self.matched_event_count,
            "matches": self.matches,
            "status": self.status,
            "message": self.message,
        }


def load_honeytoken_event_records(path: str | Path) -> list[Any]:
    event_path = Path(path)
    text = event_path.read_text(encoding="utf-8")
    if not text.strip():
        return []

    if event_path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return [{"raw": line} for line in text.splitlines() if line.strip()]

    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("events"), list):
        return payload["events"]
    return [payload]


def analyze_honeytoken_events(
    probe_payload: dict[str, Any],
    records: list[Any],
    source_path: str | Path,
) -> HoneytokenEventAnalysis:
    tokens = _extract_honeytokens(probe_payload)
    matches: list[dict[str, Any]] = []

    for index, record in enumerate(records, start=1):
        record_text = json.dumps(record, ensure_ascii=False, sort_keys=True)
        for token in tokens:
            value = str(token["value"])
            if value and value in record_text:
                matches.append(
                    {
                        "token_id": token["id"],
                        "kind": token["kind"],
                        "event_index": index,
                        "event_excerpt": _redacted_excerpt(record_text, value, token["id"]),
                    }
                )

    matched_event_count = len({match["event_index"] for match in matches})
    if not tokens:
        status = "NOT_CONFIGURED"
        message = "no external honeytokens were configured for this run"
    elif matched_event_count:
        status = "FAIL"
        message = "external honeytoken hit(s) observed; investigate possible out-of-band egress or scanning"
    else:
        status = "PASS"
        message = "no external honeytoken hits found in supplied event records"

    return HoneytokenEventAnalysis(
        source_path=str(source_path),
        checked_at=datetime.now(timezone.utc).isoformat(),
        token_count=len(tokens),
        total_records=len(records),
        matched_event_count=matched_event_count,
        matches=matches[:50],
        status=status,
        message=message,
    )


def apply_honeytoken_analysis_to_summary(
    summary: dict[str, Any],
    analysis: HoneytokenEventAnalysis,
    output_path: str | Path,
) -> dict[str, Any]:
    copied = dict(summary)
    security_analysis = dict(copied.get("security_analysis") or {})
    security_analysis["external_honeytoken_event_count"] = analysis.matched_event_count
    security_analysis["external_honeytoken_events"] = analysis.matches[:20]
    security_analysis["external_honeytoken_status"] = analysis.status
    security_analysis["external_honeytoken_message"] = analysis.message
    security_analysis["external_honeytoken_checked_at"] = analysis.checked_at
    copied["security_analysis"] = security_analysis
    copied["honeytoken_events_path"] = str(output_path)
    return copied


def _extract_honeytokens(probe_payload: dict[str, Any]) -> list[dict[str, str]]:
    tokens: list[dict[str, str]] = []
    for item in probe_payload.get("honeytokens") or []:
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        token_id = item.get("id")
        if not value or not token_id:
            continue
        tokens.append(
            {
                "id": str(token_id),
                "kind": str(item.get("kind") or "unknown"),
                "value": str(value),
            }
        )
    return tokens


def _redacted_excerpt(text: str, matched_value: str, token_id: str) -> str:
    redacted = text.replace(matched_value, f"[HONEYTOKEN:{token_id}]")
    redacted = redact_text(redacted)
    return redacted[:500]
