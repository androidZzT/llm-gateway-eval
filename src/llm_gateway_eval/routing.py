from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .models import RunResult


def analyze_routing_degradation(
    results: list[RunResult],
    official_provider: str = "official",
    quality_gap_threshold: float = 0.34,
    input_variation_ratio_threshold: float = 1.25,
    input_variation_absolute_threshold: int = 50,
) -> dict[str, Any]:
    model_variant_events = _model_variant_events(results)
    quality_gap_events = _quality_gap_events(results, official_provider, quality_gap_threshold)
    input_variation_events = _input_usage_variation_events(
        results,
        ratio_threshold=input_variation_ratio_threshold,
        absolute_threshold=input_variation_absolute_threshold,
    )
    pass_flap_events = _pass_flap_events(results)
    output_drift_events = _output_drift_events(results)
    authenticity_failure_events = _authenticity_failure_events(results, official_provider)

    strong_signal_count = (
        len(model_variant_events)
        + len(quality_gap_events)
        + len(input_variation_events)
        + len(pass_flap_events)
        + len(authenticity_failure_events)
    )
    medium_signal_count = len(output_drift_events)
    risk_level = _risk_level(strong_signal_count, medium_signal_count)

    return {
        "risk_level": risk_level,
        "strong_signal_count": strong_signal_count,
        "medium_signal_count": medium_signal_count,
        "model_variant_event_count": len(model_variant_events),
        "model_variant_events": model_variant_events[:20],
        "quality_gap_event_count": len(quality_gap_events),
        "quality_gap_events": quality_gap_events[:30],
        "input_usage_variation_event_count": len(input_variation_events),
        "input_usage_variation_events": input_variation_events[:30],
        "pass_flap_event_count": len(pass_flap_events),
        "pass_flap_events": pass_flap_events[:30],
        "output_drift_event_count": len(output_drift_events),
        "output_drift_events": output_drift_events[:30],
        "authenticity_failure_event_count": len(authenticity_failure_events),
        "authenticity_failure_events": authenticity_failure_events[:30],
        "notes": [
            "These are black-box routing/degradation signals, not proof of upstream routing decisions.",
            "Quality gaps are strongest when an official direct baseline is present and run with the same cases.",
            "Output drift at temperature 0 is a soft signal; model variants, input-token variation, and pass/fail flaps are stronger.",
        ],
    }


def _model_variant_events(results: list[RunResult]) -> list[dict[str, Any]]:
    provider_groups: dict[str, list[RunResult]] = defaultdict(list)
    for result in results:
        provider_groups[result.provider].append(result)

    events: list[dict[str, Any]] = []
    for provider, items in sorted(provider_groups.items()):
        response_models = Counter(result.model for result in items if result.model)
        requested_models = Counter(result.requested_model for result in items if result.requested_model)
        mismatch_count = sum(
            1
            for result in items
            if result.requested_model and result.model and result.requested_model != result.model
        )
        if len(response_models) > 1 or mismatch_count:
            events.append(
                {
                    "provider": provider,
                    "requested_models": dict(sorted(requested_models.items())),
                    "response_models": dict(sorted(response_models.items())),
                    "mismatch_count": mismatch_count,
                    "signal": "provider returned multiple model names or names different from requested model",
                }
            )
    return events


def _quality_gap_events(
    results: list[RunResult],
    official_provider: str,
    quality_gap_threshold: float,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, list[RunResult]]] = defaultdict(lambda: defaultdict(list))
    for result in results:
        grouped[result.case_id][result.provider].append(result)

    events: list[dict[str, Any]] = []
    for case_id, providers in sorted(grouped.items()):
        official = providers.get(official_provider)
        if not official:
            continue
        official_rate = _pass_rate(official)
        if official_rate < 0.67:
            continue
        for provider, items in sorted(providers.items()):
            if provider == official_provider:
                continue
            provider_rate = _pass_rate(items)
            gap = official_rate - provider_rate
            if gap >= quality_gap_threshold:
                sample = items[0]
                events.append(
                    {
                        "provider": provider,
                        "case_id": case_id,
                        "category": sample.category,
                        "tags": sample.tags,
                        "official_pass_rate": official_rate,
                        "provider_pass_rate": provider_rate,
                        "gap": round(gap, 6),
                        "signal": "official baseline passes substantially more often than provider",
                    }
                )
    return events


def _input_usage_variation_events(
    results: list[RunResult],
    ratio_threshold: float,
    absolute_threshold: int,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[int]] = defaultdict(list)
    for result in results:
        if result.usage.input_tokens is not None:
            grouped[(result.provider, result.case_id)].append(result.usage.input_tokens)

    events: list[dict[str, Any]] = []
    for (provider, case_id), values in sorted(grouped.items()):
        if len(values) < 2:
            continue
        minimum = min(values)
        maximum = max(values)
        delta = maximum - minimum
        ratio = None if minimum <= 0 else maximum / minimum
        if delta >= absolute_threshold and ratio is not None and ratio >= ratio_threshold:
            events.append(
                {
                    "provider": provider,
                    "case_id": case_id,
                    "min_input_tokens": minimum,
                    "max_input_tokens": maximum,
                    "delta": delta,
                    "ratio": round(ratio, 4),
                    "signal": "same case has large input-token variation across repeats",
                }
            )
    return events


def _pass_flap_events(results: list[RunResult]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[RunResult]] = defaultdict(list)
    for result in results:
        grouped[(result.provider, result.case_id)].append(result)

    events: list[dict[str, Any]] = []
    for (provider, case_id), items in sorted(grouped.items()):
        if len(items) < 2:
            continue
        pass_count = sum(1 for item in items if item.passed())
        if 0 < pass_count < len(items):
            sample = items[0]
            events.append(
                {
                    "provider": provider,
                    "case_id": case_id,
                    "category": sample.category,
                    "pass_count": pass_count,
                    "result_count": len(items),
                    "pass_rate": round(pass_count / len(items), 6),
                    "signal": "same case alternates between pass and fail across repeats",
                }
            )
    return events


def _output_drift_events(results: list[RunResult]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[RunResult]] = defaultdict(list)
    for result in results:
        if result.error is None and result.output:
            grouped[(result.provider, result.case_id)].append(result)

    events: list[dict[str, Any]] = []
    for (provider, case_id), items in sorted(grouped.items()):
        if len(items) < 2:
            continue
        normalized_outputs = {_normalize_output(item.output) for item in items}
        if len(normalized_outputs) > 1:
            sample = items[0]
            events.append(
                {
                    "provider": provider,
                    "case_id": case_id,
                    "category": sample.category,
                    "result_count": len(items),
                    "unique_output_count": len(normalized_outputs),
                    "all_passed": all(item.passed() for item in items),
                    "signal": "temperature-0 repeats produced different normalized outputs",
                }
            )
    return events


def _authenticity_failure_events(results: list[RunResult], official_provider: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for result in results:
        labels = {result.category.lower(), *(tag.lower() for tag in result.tags)}
        if result.provider == official_provider or not (labels & {"model_authenticity", "authenticity", "fingerprint", "capability_probe"}):
            continue
        if not result.passed():
            events.append(
                {
                    "provider": result.provider,
                    "case_id": result.case_id,
                    "repeat_index": result.repeat_index,
                    "category": result.category,
                    "model": result.model,
                    "requested_model": result.requested_model,
                    "signal": "model-authenticity probe failed for provider",
                }
            )
    return events


def _risk_level(strong_signal_count: int, medium_signal_count: int) -> str:
    if strong_signal_count >= 3:
        return "HIGH"
    if strong_signal_count >= 1 or medium_signal_count >= 3:
        return "MEDIUM"
    return "LOW"


def _pass_rate(results: list[RunResult]) -> float:
    return 0.0 if not results else round(sum(1 for result in results if result.passed()) / len(results), 6)


def _normalize_output(output: str) -> str:
    return " ".join(output.strip().split()).lower()
