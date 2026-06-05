from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from .models import EvalConfig, Pricing, RunResult, Usage


SECURITY_LABELS = {"safety", "security", "privacy", "prompt-injection"}
MODEL_AUTHENTICITY_LABELS = {"model_authenticity", "authenticity", "fingerprint", "capability_probe"}
NETWORK_ERROR_TYPES = {"network", "timeout", "tls"}
MODEL_INVOCATION_ERROR_TYPES = {"http_429", "http_4xx", "http_5xx", "http_status", "model_response"}


def calculate_cost(usage: Usage, pricing: Pricing) -> float:
    input_tokens = usage.input_tokens or 0
    output_tokens = usage.output_tokens or 0
    return (
        input_tokens * pricing.input_per_million / 1_000_000
        + output_tokens * pricing.output_per_million / 1_000_000
    )


def aggregate_results(config: EvalConfig, results: list[RunResult]) -> dict[str, Any]:
    provider_groups: dict[str, list[RunResult]] = defaultdict(list)
    category_groups: dict[str, list[RunResult]] = defaultdict(list)
    for result in results:
        provider_groups[result.provider].append(result)
        category_groups[result.category].append(result)

    providers = {
        provider: _summarise_group(items, config)
        for provider, items in sorted(provider_groups.items())
    }
    _add_cost_scores(providers)
    _add_overall_scores(providers, config)

    return {
        "title": config.report.title,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_results": len(results),
        "total_cost": round(sum(result.cost for result in results), 8),
        "currency": _first_currency(results),
        "providers": providers,
        "categories": {
            category: _summarise_group(items, config, include_scores=False)
            for category, items in sorted(category_groups.items())
        },
        "weights": config.report.weights.__dict__,
        "run_options": config.run.__dict__,
    }


def _summarise_group(
    results: list[RunResult],
    config: EvalConfig,
    include_scores: bool = True,
) -> dict[str, Any]:
    total = len(results)
    if total == 0:
        return {}

    no_error = [result for result in results if result.error is None]
    passed = [result for result in results if result.passed()]
    latencies = [result.latency_seconds for result in results if result.latency_seconds is not None]
    ttfts = [result.ttft_seconds for result in results if result.ttft_seconds is not None]
    assertion_results = [
        assertion
        for result in results
        for assertion in result.assertion_results
    ]
    json_schema_assertions = [
        assertion for assertion in assertion_results if assertion.type == "json_schema"
    ]
    security_results = [
        result for result in results if _is_security_result(result)
    ]
    authenticity_results = [
        result for result in results if _is_model_authenticity_result(result)
    ]
    error_types: dict[str, int] = defaultdict(int)
    for result in results:
        if result.error_type:
            error_types[result.error_type] += 1
    usage_present_count = sum(
        1
        for result in results
        if result.usage.input_tokens is not None
        or result.usage.output_tokens is not None
        or result.usage.total_tokens is not None
    )
    output_tokens = sum(result.usage.output_tokens or 0 for result in results)
    total_latency = sum(latencies)

    summary: dict[str, Any] = {
        "total": total,
        "request_success_count": len(no_error),
        "request_success_rate": _ratio(len(no_error), total),
        "case_pass_count": len(passed),
        "case_pass_rate": _ratio(len(passed), total),
        "error_count": total - len(no_error),
        "error_types": dict(sorted(error_types.items())),
        "network_error_count": sum(error_types.get(error_type, 0) for error_type in NETWORK_ERROR_TYPES),
        "model_invocation_error_count": sum(
            error_types.get(error_type, 0) for error_type in MODEL_INVOCATION_ERROR_TYPES
        ),
        "model_name_mismatch_count": sum(
            1
            for result in results
            if result.requested_model and result.model and result.requested_model != result.model
        ),
        "assertion_total": len(assertion_results),
        "assertion_pass_count": sum(1 for assertion in assertion_results if assertion.passed),
        "assertion_pass_rate": _optional_ratio(
            sum(1 for assertion in assertion_results if assertion.passed),
            len(assertion_results),
        ),
        "json_schema_total": len(json_schema_assertions),
        "json_schema_pass_rate": _optional_ratio(
            sum(1 for assertion in json_schema_assertions if assertion.passed),
            len(json_schema_assertions),
        ),
        "usage_present_rate": _ratio(usage_present_count, total),
        "latency": {
            "p50": _percentile(latencies, 50),
            "p95": _percentile(latencies, 95),
            "p99": _percentile(latencies, 99),
            "avg": round(sum(latencies) / len(latencies), 6) if latencies else None,
        },
        "ttft": {
            "p50": _percentile(ttfts, 50),
            "p95": _percentile(ttfts, 95),
        },
        "tokens_per_second": round(output_tokens / total_latency, 6) if total_latency > 0 else None,
        "total_input_tokens": sum(result.usage.input_tokens or 0 for result in results),
        "total_output_tokens": output_tokens,
        "total_cost": round(sum(result.cost for result in results), 8),
        "currency": _first_currency(results),
        "security_case_total": len(security_results),
        "security_case_pass_rate": _optional_ratio(
            sum(1 for result in security_results if result.passed()),
            len(security_results),
        ),
        "model_authenticity_case_total": len(authenticity_results),
        "model_authenticity_case_pass_rate": _optional_ratio(
            sum(1 for result in authenticity_results if result.passed()),
            len(authenticity_results),
        ),
    }

    if include_scores:
        summary["scores"] = _scores_without_cost(summary, config)
    return summary


def _scores_without_cost(summary: dict[str, Any], config: EvalConfig) -> dict[str, float]:
    quality = summary["assertion_pass_rate"]
    if quality is None:
        quality = summary["case_pass_rate"]

    p95_target = float(config.run.performance_targets.get("p95_latency_seconds", 8))
    p95_latency = summary["latency"]["p95"]
    if p95_latency is None or p95_latency <= 0:
        performance = 0.0
    else:
        performance = min(1.0, p95_target / p95_latency)

    security = summary["security_case_pass_rate"]
    if security is None:
        security = 0.6

    return {
        "quality": round(quality * 100, 2),
        "reliability": round(summary["request_success_rate"] * 100, 2),
        "performance": round(performance * 100, 2),
        "cost": 0.0,
        "security_compliance": round(security * 100, 2),
        "operations": 60.0,
    }


def _add_cost_scores(providers: dict[str, dict[str, Any]]) -> None:
    nonzero_costs = [
        provider["total_cost"]
        for provider in providers.values()
        if provider["total_cost"] > 0
    ]
    min_nonzero = min(nonzero_costs) if nonzero_costs else 0.0
    for provider in providers.values():
        cost = provider["total_cost"]
        if cost <= 0:
            score = 100.0
        elif min_nonzero <= 0:
            score = 100.0
        else:
            score = min(100.0, (min_nonzero / cost) * 100)
        provider.setdefault("scores", {})["cost"] = round(score, 2)


def _add_overall_scores(providers: dict[str, dict[str, Any]], config: EvalConfig) -> None:
    weights = config.report.weights.__dict__
    weight_total = sum(float(value) for value in weights.values()) or 1.0
    for provider in providers.values():
        scores = provider.get("scores", {})
        weighted = sum(scores.get(name, 0.0) * float(weight) for name, weight in weights.items())
        provider["overall_score"] = round(weighted / weight_total, 2)


def _is_security_result(result: RunResult) -> bool:
    labels = {result.category.lower(), *(tag.lower() for tag in result.tags)}
    return bool(labels & SECURITY_LABELS)


def _is_model_authenticity_result(result: RunResult) -> bool:
    labels = {result.category.lower(), *(tag.lower() for tag in result.tags)}
    return bool(labels & MODEL_AUTHENTICITY_LABELS)


def _ratio(numerator: int, denominator: int) -> float:
    return 0.0 if denominator == 0 else round(numerator / denominator, 6)


def _optional_ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return _ratio(numerator, denominator)


def _percentile(values: list[float], percentile: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = math.ceil((percentile / 100) * len(ordered)) - 1
    index = min(max(index, 0), len(ordered) - 1)
    return round(ordered[index], 6)


def _first_currency(results: list[RunResult]) -> str:
    return results[0].currency if results else "USD"
