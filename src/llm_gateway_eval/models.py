from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


JsonDict = dict[str, Any]
Message = dict[str, Any]


@dataclass(frozen=True)
class AssertionSpec:
    type: str
    value: Any | None = None
    schema: JsonDict | None = None
    flags: str | None = None


@dataclass(frozen=True)
class EvalCase:
    id: str
    category: str
    messages: list[Message]
    expected: Any | None = None
    assertions: list[AssertionSpec] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Pricing:
    input_per_million: float = 0.0
    output_per_million: float = 0.0
    currency: str = "USD"


@dataclass(frozen=True)
class ProviderTarget:
    name: str
    base_url: str
    api_key_env: str
    model: str
    headers: dict[str, str] = field(default_factory=dict)
    params: JsonDict = field(default_factory=dict)
    pricing: Pricing = field(default_factory=Pricing)


@dataclass(frozen=True)
class RunOptions:
    timeout_seconds: float = 60.0
    concurrency: int = 2
    attempts: int = 1
    repeat_per_case: int = 1
    stream: bool = False
    performance_targets: JsonDict = field(default_factory=dict)


@dataclass(frozen=True)
class ReportWeights:
    quality: float = 0.25
    reliability: float = 0.25
    performance: float = 0.15
    cost: float = 0.15
    security_compliance: float = 0.15
    operations: float = 0.05


@dataclass(frozen=True)
class ReportOptions:
    title: str = "Large Model Gateway Evaluation Report"
    weights: ReportWeights = field(default_factory=ReportWeights)


@dataclass(frozen=True)
class EvalConfig:
    run: RunOptions
    targets: list[ProviderTarget]
    report: ReportOptions


@dataclass(frozen=True)
class AssertionResult:
    type: str
    passed: bool
    message: str


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class RunResult:
    case_id: str
    category: str
    tags: list[str]
    provider: str
    model: str
    output: str
    usage: Usage
    latency_seconds: float | None
    ttft_seconds: float | None
    error: str | None
    attempts: int
    assertion_results: list[AssertionResult]
    cost: float
    currency: str
    requested_model: str = ""
    repeat_index: int = 1
    error_type: str | None = None

    def passed(self) -> bool:
        return self.error is None and all(result.passed for result in self.assertion_results)

    def to_dict(self) -> JsonDict:
        payload = asdict(self)
        payload["passed"] = self.passed()
        return payload
