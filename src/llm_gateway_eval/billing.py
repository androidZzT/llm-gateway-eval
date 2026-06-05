from __future__ import annotations

import json
import math
from collections import defaultdict
from typing import Any, Iterable

from .models import EvalCase, EvalConfig, RunResult


TOKEN_FIELDS = ("input_tokens", "output_tokens", "total_tokens")


def analyze_usage_billing(
    config: EvalConfig,
    cases: Iterable[EvalCase],
    results: list[RunResult],
    official_provider: str = "official",
    input_ratio_threshold: float = 1.25,
    input_absolute_threshold: int = 50,
) -> dict[str, Any]:
    case_estimates = {
        case.id: {
            "prompt_tokens": _rough_token_count(json.dumps(case.messages, ensure_ascii=False, sort_keys=True)),
        }
        for case in cases
    }
    provider_groups: dict[str, list[RunResult]] = defaultdict(list)
    for result in results:
        provider_groups[result.provider].append(result)

    total_consistency_issues = _total_consistency_issues(results)
    rough_estimate_anomalies = _rough_estimate_anomalies(results, case_estimates)
    paired_discrepancies = _paired_usage_discrepancies(
        results,
        official_provider=official_provider,
        input_ratio_threshold=input_ratio_threshold,
        input_absolute_threshold=input_absolute_threshold,
    )

    return {
        "checked_result_count": len(results),
        "provider_usage": {
            provider: _provider_usage_summary(items, case_estimates)
            for provider, items in sorted(provider_groups.items())
        },
        "baseline_provider": official_provider,
        "paired_comparison_count": _paired_comparison_count(results, official_provider),
        "paired_usage_discrepancy_count": len(paired_discrepancies),
        "paired_usage_discrepancies": paired_discrepancies[:30],
        "total_consistency_issue_count": len(total_consistency_issues),
        "total_consistency_issues": total_consistency_issues[:30],
        "rough_estimate_anomaly_count": len(rough_estimate_anomalies),
        "rough_estimate_anomalies": rough_estimate_anomalies[:30],
        "notes": [
            "Input-token discrepancies versus an official baseline are stronger evidence than output/total discrepancies.",
            "Rough local token estimates are heuristic guardrails for gross anomalies, not vendor-grade billing truth.",
            "To prove final charges, import or reconcile the gateway's account-level billing ledger when available.",
        ],
    }


def _provider_usage_summary(results: list[RunResult], case_estimates: dict[str, dict[str, int]]) -> dict[str, Any]:
    total = len(results)
    usage_any = sum(1 for result in results if _has_any_usage(result))
    usage_complete = sum(1 for result in results if _has_complete_usage(result))
    consistency_issues = _total_consistency_issues(results)
    estimated_input = sum(case_estimates.get(result.case_id, {}).get("prompt_tokens", 0) for result in results)
    reported_input = sum(result.usage.input_tokens or 0 for result in results)
    reported_output = sum(result.usage.output_tokens or 0 for result in results)
    reported_total = sum(result.usage.total_tokens or 0 for result in results)
    return {
        "result_count": total,
        "usage_any_rate": _ratio(usage_any, total),
        "usage_complete_rate": _ratio(usage_complete, total),
        "reported_input_tokens": reported_input,
        "reported_output_tokens": reported_output,
        "reported_total_tokens": reported_total,
        "rough_estimated_prompt_tokens": estimated_input,
        "reported_input_to_rough_estimate_ratio": _safe_ratio(reported_input, estimated_input),
        "total_consistency_issue_count": len(consistency_issues),
    }


def _paired_usage_discrepancies(
    results: list[RunResult],
    official_provider: str,
    input_ratio_threshold: float,
    input_absolute_threshold: int,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], dict[str, RunResult]] = defaultdict(dict)
    for result in results:
        grouped[(result.case_id, result.repeat_index)][result.provider] = result

    discrepancies: list[dict[str, Any]] = []
    field_thresholds = {
        "input_tokens": (input_ratio_threshold, input_absolute_threshold),
        "output_tokens": (1.75, 80),
        "total_tokens": (1.5, 100),
    }
    for (case_id, repeat_index), providers in sorted(grouped.items()):
        official = providers.get(official_provider)
        if official is None:
            continue
        for provider, result in sorted(providers.items()):
            if provider == official_provider:
                continue
            for field in TOKEN_FIELDS:
                official_value = getattr(official.usage, field)
                provider_value = getattr(result.usage, field)
                if official_value is None or provider_value is None:
                    continue
                ratio_threshold, absolute_threshold = field_thresholds[field]
                delta = provider_value - official_value
                larger_ratio = _larger_ratio(provider_value, official_value)
                if abs(delta) >= absolute_threshold and larger_ratio is not None and larger_ratio >= ratio_threshold:
                    discrepancies.append(
                        {
                            "provider": provider,
                            "case_id": case_id,
                            "repeat_index": repeat_index,
                            "field": field,
                            "official_value": official_value,
                            "provider_value": provider_value,
                            "delta": delta,
                            "ratio": round(provider_value / official_value, 4) if official_value else None,
                            "signal": (
                                "provider reports more tokens than official baseline"
                                if delta > 0
                                else "provider reports fewer tokens than official baseline"
                            ),
                            "strength": "strong" if field == "input_tokens" else "medium",
                        }
                    )
    return discrepancies


def _paired_comparison_count(results: list[RunResult], official_provider: str) -> int:
    grouped: dict[tuple[str, int], set[str]] = defaultdict(set)
    for result in results:
        grouped[(result.case_id, result.repeat_index)].add(result.provider)
    return sum(
        len(providers - {official_provider})
        for providers in grouped.values()
        if official_provider in providers
    )


def _total_consistency_issues(results: list[RunResult]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for result in results:
        input_tokens = result.usage.input_tokens
        output_tokens = result.usage.output_tokens
        total_tokens = result.usage.total_tokens
        if input_tokens is None or output_tokens is None or total_tokens is None:
            continue
        expected = input_tokens + output_tokens
        delta = total_tokens - expected
        if abs(delta) > 1:
            issues.append(
                {
                    "provider": result.provider,
                    "case_id": result.case_id,
                    "repeat_index": result.repeat_index,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens,
                    "expected_total_tokens": expected,
                    "delta": delta,
                }
            )
    return issues


def _rough_estimate_anomalies(
    results: list[RunResult],
    case_estimates: dict[str, dict[str, int]],
) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    for result in results:
        prompt_estimate = case_estimates.get(result.case_id, {}).get("prompt_tokens")
        if prompt_estimate and result.usage.input_tokens is not None:
            _maybe_add_rough_anomaly(
                anomalies,
                result,
                field="input_tokens",
                reported=result.usage.input_tokens,
                estimated=prompt_estimate,
            )
        output_estimate = _rough_token_count(result.output)
        if output_estimate and result.usage.output_tokens is not None:
            _maybe_add_rough_anomaly(
                anomalies,
                result,
                field="output_tokens",
                reported=result.usage.output_tokens,
                estimated=output_estimate,
            )
    return anomalies


def _maybe_add_rough_anomaly(
    anomalies: list[dict[str, Any]],
    result: RunResult,
    field: str,
    reported: int,
    estimated: int,
) -> None:
    ratio = _safe_ratio(reported, estimated)
    if ratio is None:
        return
    delta = reported - estimated
    if (ratio >= 4.0 and delta >= 100) or (ratio <= 0.25 and delta <= -50):
        anomalies.append(
            {
                "provider": result.provider,
                "case_id": result.case_id,
                "repeat_index": result.repeat_index,
                "field": field,
                "reported": reported,
                "rough_estimate": estimated,
                "ratio": ratio,
                "signal": "reported usage is far from rough local estimate",
            }
        )


def _rough_token_count(text: str) -> int:
    if not text:
        return 0
    cjk = 0
    ascii_chars = 0
    other = 0
    for character in text:
        codepoint = ord(character)
        if _is_cjk(codepoint):
            cjk += 1
        elif codepoint < 128:
            ascii_chars += 1
        else:
            other += 1
    return max(1, math.ceil(cjk + ascii_chars / 4 + other / 2))


def _is_cjk(codepoint: int) -> bool:
    return (
        0x4E00 <= codepoint <= 0x9FFF
        or 0x3400 <= codepoint <= 0x4DBF
        or 0xF900 <= codepoint <= 0xFAFF
    )


def _has_any_usage(result: RunResult) -> bool:
    return any(getattr(result.usage, field) is not None for field in TOKEN_FIELDS)


def _has_complete_usage(result: RunResult) -> bool:
    return all(getattr(result.usage, field) is not None for field in TOKEN_FIELDS)


def _larger_ratio(left: int, right: int) -> float | None:
    if left <= 0 or right <= 0:
        return None
    return max(left / right, right / left)


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _ratio(numerator: int, denominator: int) -> float:
    return 0.0 if denominator == 0 else round(numerator / denominator, 6)
