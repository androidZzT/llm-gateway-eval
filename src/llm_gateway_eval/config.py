from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from .models import (
    EvalConfig,
    Pricing,
    ProviderTarget,
    ReportOptions,
    ReportWeights,
    RunOptions,
)


class ConfigError(ValueError):
    pass


def load_config(path: str | Path) -> EvalConfig:
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError(f"Config must be a YAML mapping: {config_path}")

    targets_raw = raw.get("targets")
    if not isinstance(targets_raw, list) or not targets_raw:
        raise ConfigError("Config must contain at least one target.")

    run_raw = _mapping(raw.get("run", {}), "run")
    report_raw = _mapping(raw.get("report", {}), "report")
    weights_raw = _mapping(report_raw.get("weights", {}), "report.weights")

    run = RunOptions(
        timeout_seconds=float(run_raw.get("timeout_seconds", 60)),
        concurrency=max(1, int(run_raw.get("concurrency", 2))),
        attempts=max(1, int(run_raw.get("attempts", 1))),
        repeat_per_case=max(1, int(run_raw.get("repeat_per_case", 1))),
        stream=bool(run_raw.get("stream", False)),
        performance_targets=_mapping(run_raw.get("performance_targets", {}), "run.performance_targets"),
    )
    report = ReportOptions(
        title=str(report_raw.get("title", "Large Model Gateway Evaluation Report")),
        weights=ReportWeights(
            quality=float(weights_raw.get("quality", 0.25)),
            reliability=float(weights_raw.get("reliability", 0.25)),
            performance=float(weights_raw.get("performance", 0.15)),
            cost=float(weights_raw.get("cost", 0.15)),
            security_compliance=float(weights_raw.get("security_compliance", 0.15)),
            operations=float(weights_raw.get("operations", 0.05)),
        ),
    )

    targets = [_parse_target(index, item) for index, item in enumerate(targets_raw)]
    return EvalConfig(run=run, targets=targets, report=report)


def missing_api_key_envs(config: EvalConfig) -> list[str]:
    missing: list[str] = []
    for target in config.targets:
        if not os.getenv(target.api_key_env):
            missing.append(target.api_key_env)
    return sorted(set(missing))


def validate_config_env(config: EvalConfig) -> None:
    missing = missing_api_key_envs(config)
    if missing:
        joined = ", ".join(missing)
        raise ConfigError(f"Missing API key environment variable(s): {joined}")


def _parse_target(index: int, raw: Any) -> ProviderTarget:
    mapping = _mapping(raw, f"targets[{index}]")
    required = ["name", "base_url", "api_key_env", "model"]
    missing = [key for key in required if not mapping.get(key)]
    if missing:
        raise ConfigError(f"targets[{index}] missing required field(s): {', '.join(missing)}")

    pricing_raw = _mapping(mapping.get("pricing", {}), f"targets[{index}].pricing")
    return ProviderTarget(
        name=str(mapping["name"]),
        base_url=str(mapping["base_url"]).rstrip("/"),
        api_key_env=str(mapping["api_key_env"]),
        model=str(mapping["model"]),
        headers={str(k): str(v) for k, v in _mapping(mapping.get("headers", {}), f"targets[{index}].headers").items()},
        params=_mapping(mapping.get("params", {}), f"targets[{index}].params"),
        pricing=Pricing(
            input_per_million=float(pricing_raw.get("input_per_million", 0)),
            output_per_million=float(pricing_raw.get("output_per_million", 0)),
            currency=str(pricing_raw.get("currency", "USD")),
        ),
    )


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{label} must be a mapping.")
    return value
