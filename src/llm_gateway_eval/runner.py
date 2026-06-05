from __future__ import annotations

import asyncio
from typing import Iterable

import httpx

from .assertions import evaluate_assertions
from .client import OpenAICompatibleClient
from .metrics import calculate_cost
from .models import EvalCase, EvalConfig, ProviderTarget, RunResult, Usage
from .redaction import redact_text


async def run_evaluation(config: EvalConfig, cases: Iterable[EvalCase]) -> list[RunResult]:
    eval_cases = list(cases)
    semaphore = asyncio.Semaphore(config.run.concurrency)
    tasks = [
        _run_one(semaphore, config, target, case, repeat_index)
        for target in config.targets
        for case in eval_cases
        for repeat_index in range(1, config.run.repeat_per_case + 1)
    ]
    return list(await asyncio.gather(*tasks))


async def _run_one(
    semaphore: asyncio.Semaphore,
    config: EvalConfig,
    target: ProviderTarget,
    case: EvalCase,
    repeat_index: int,
) -> RunResult:
    async with semaphore:
        client = OpenAICompatibleClient(target, config.run)
        last_error: str | None = None
        last_error_type: str | None = None
        for attempt in range(1, config.run.attempts + 1):
            try:
                response = await client.complete(case)
                assertion_results = evaluate_assertions(case, response.output)
                return RunResult(
                    case_id=case.id,
                    category=case.category,
                    tags=case.tags,
                    provider=target.name,
                    model=response.model,
                    output=redact_text(response.output),
                    usage=response.usage,
                    latency_seconds=response.latency_seconds,
                    ttft_seconds=response.ttft_seconds,
                    error=None,
                    attempts=attempt,
                    assertion_results=assertion_results,
                    cost=calculate_cost(response.usage, target.pricing),
                    currency=target.pricing.currency,
                    requested_model=target.model,
                    repeat_index=repeat_index,
                    error_type=None,
                )
            except Exception as exc:  # noqa: BLE001 - preserve eval progress per case.
                last_error = redact_text(_format_exception(exc))
                last_error_type = _classify_exception(exc)
                if attempt < config.run.attempts:
                    await asyncio.sleep(min(0.5 * attempt, 2.0))

        return RunResult(
            case_id=case.id,
            category=case.category,
            tags=case.tags,
            provider=target.name,
            model=target.model,
            output="",
            usage=Usage(),
            latency_seconds=None,
            ttft_seconds=None,
            error=last_error or "unknown error",
            attempts=config.run.attempts,
            assertion_results=[],
            cost=0.0,
            currency=target.pricing.currency,
            requested_model=target.model,
            repeat_index=repeat_index,
            error_type=last_error_type or "unknown",
        )


def _format_exception(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        body = exc.response.text[:500].replace("\n", " ")
        return f"HTTP {exc.response.status_code}: {body}"
    if isinstance(exc, httpx.RequestError):
        return f"{exc.__class__.__name__}: {exc}"
    return f"{exc.__class__.__name__}: {exc}"


def _classify_exception(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        message = str(exc).lower()
        if "ssl" in message or "certificate" in message or "tls" in message:
            return "tls"
        return "network"
    if isinstance(exc, httpx.NetworkError):
        return "network"
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 429:
            return "http_429"
        if 500 <= status <= 599:
            return "http_5xx"
        if 400 <= status <= 499:
            return "http_4xx"
        return "http_status"
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        return "model_response"
    return "unknown"
