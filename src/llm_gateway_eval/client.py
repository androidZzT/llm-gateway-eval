from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .models import EvalCase, ProviderTarget, RunOptions, Usage


@dataclass(frozen=True)
class ClientResponse:
    output: str
    usage: Usage
    latency_seconds: float
    ttft_seconds: float | None
    model: str


class OpenAICompatibleClient:
    def __init__(self, target: ProviderTarget, options: RunOptions):
        self.target = target
        self.options = options

    async def complete(self, case: EvalCase) -> ClientResponse:
        api_key = os.getenv(self.target.api_key_env, "")
        headers = {
            "Content-Type": "application/json",
            **self.target.headers,
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": self.target.model,
            "messages": case.messages,
            **self.target.params,
        }
        payload["stream"] = bool(payload.get("stream", self.options.stream))

        url = f"{self.target.base_url}/chat/completions"
        timeout = httpx.Timeout(self.options.timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            if payload["stream"]:
                return await self._stream_completion(client, url, headers, payload)
            return await self._completion(client, url, headers, payload)

    async def _completion(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> ClientResponse:
        started = time.perf_counter()
        response = await client.post(url, headers=headers, json=payload)
        latency = time.perf_counter() - started
        response.raise_for_status()
        body = response.json()
        return ClientResponse(
            output=_extract_output(body),
            usage=_extract_usage(body),
            latency_seconds=latency,
            ttft_seconds=None,
            model=str(body.get("model") or payload["model"]),
        )

    async def _stream_completion(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> ClientResponse:
        started = time.perf_counter()
        first_chunk_at: float | None = None
        content_parts: list[str] = []
        usage = Usage()
        response_model = str(payload["model"])

        async with client.stream("POST", url, headers=headers, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    break
                if not data:
                    continue
                chunk = json.loads(data)
                response_model = str(chunk.get("model") or response_model)
                if first_chunk_at is None:
                    first_chunk_at = time.perf_counter()
                content = _extract_stream_delta(chunk)
                if content:
                    content_parts.append(content)
                if chunk.get("usage"):
                    usage = _extract_usage(chunk)

        latency = time.perf_counter() - started
        ttft = None if first_chunk_at is None else first_chunk_at - started
        return ClientResponse(
            output="".join(content_parts),
            usage=usage,
            latency_seconds=latency,
            ttft_seconds=ttft,
            model=response_model,
        )


def _extract_output(body: dict[str, Any]) -> str:
    choices = body.get("choices") or []
    if not choices:
        return ""
    choice = choices[0] or {}
    message = choice.get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    if content is None:
        return ""
    return str(content)


def _extract_stream_delta(chunk: dict[str, Any]) -> str:
    choices = chunk.get("choices") or []
    if not choices:
        return ""
    delta = (choices[0] or {}).get("delta") or {}
    content = delta.get("content")
    return "" if content is None else str(content)


def _extract_usage(body: dict[str, Any]) -> Usage:
    raw = body.get("usage") or {}
    input_tokens = raw.get("prompt_tokens", raw.get("input_tokens"))
    output_tokens = raw.get("completion_tokens", raw.get("output_tokens"))
    total_tokens = raw.get("total_tokens")
    if total_tokens is None and (input_tokens is not None or output_tokens is not None):
        total_tokens = (input_tokens or 0) + (output_tokens or 0)
    return Usage(
        input_tokens=_to_int_or_none(input_tokens),
        output_tokens=_to_int_or_none(output_tokens),
        total_tokens=_to_int_or_none(total_tokens),
    )


def _to_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

