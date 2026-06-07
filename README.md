# llm-gateway-eval

[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![API](https://img.shields.io/badge/API-OpenAI--compatible-412991.svg)](https://platform.openai.com/docs/api-reference/chat)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

When you hand real code and real money to an OpenAI-compatible gateway, four worries follow you:
**is the model the one you paid for, is your data safe, is it stable, and is the price honest?**
`llm-gateway-eval` turns each worry into a runnable, evidence-backed check.

It replays the same JSONL eval cases against your gateway — and, optionally, a direct-provider
baseline — then captures model-authenticity signals, privacy/security probes, latency and error
stats, and token/cost accuracy, and renders it all into a Markdown report you can read or share.

| Worry | What it checks |
| --- | --- |
| **Is the model swapped?** | Model-authenticity probes and response-metadata checks, with optional side-by-side comparison against the official provider. |
| **Is my data safe?** | Transport audit (HTTPS/TLS, certificate, static-secret headers), privacy/security cases, optional out-of-band honeytoken egress monitoring, and output redaction. |
| **Is it stable?** | Repeated runs with P50/P95/P99 latency, error classes, retries, and request success rate. |
| **Is the price honest?** | Token-usage completeness and estimated input/output cost deltas versus the baseline. |

## Table of Contents

- [Installation](#installation)
- [60-Second Quickstart](#60-second-quickstart)
- [Usage](#usage)
  - [Add a direct-provider baseline](#add-a-direct-provider-baseline)
  - [Out-of-band leakage (honeytokens)](#out-of-band-leakage-honeytokens)
  - [Full YAML workflow](#full-yaml-workflow)
  - [Codex and coding-agent comparison](#codex-and-coding-agent-comparison)
  - [Website task benchmark](#website-task-benchmark)
- [What It Measures](#what-it-measures)
- [Case Format](#case-format)
- [Project Layout](#project-layout)
- [Notes & Limitations](#notes--limitations)
- [License](#license)

## Installation

Requires **Python 3.11+** and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/androidZzT/llm-gateway-eval.git
cd llm-gateway-eval
uv sync
```

## 60-Second Quickstart

Point the tool at a gateway with just a URL, an API key, and a model name:

```bash
uv run llm-gateway-eval gateway-quick-eval \
  --gateway-url https://gateway.example.com/v1 \
  --gateway-api-key "..." \
  --model gpt-5.5
```

That single command audits transport, runs the core eval cases plus dynamic security probes, and
writes:

- `runs/gateway-quick-eval/quick_config.json` — the resolved run configuration (env var names only, no keys).
- `runs/gateway-quick-eval/audit.json` — HTTPS/TLS, key-handling, and static-secret checks.
- `runs/gateway-quick-eval/security_probes.json` — per-run canary and tamper probe definitions.
- `runs/gateway-quick-eval/results.jsonl` — per-case evidence for authenticity, privacy/security, and stability.
- `runs/gateway-quick-eval/summary.json` — pass rates, latency, error classes, usage/billing, routing/degradation, security analysis, and scores.
- `reports/gateway-quick-eval.md` — the human-readable report.

> Prefer `--gateway-api-key-env GATEWAY_API_KEY` (or `--gateway-api-key-env <YOUR_VAR>`) over
> passing the raw key on the command line, so secrets stay out of your shell history.

## Usage

### Add a direct-provider baseline

The quickest way to tell whether a gateway is swapping or degrading the model is to run it
side by side with the official provider in the same run:

```bash
export OPENAI_API_KEY="..."

uv run llm-gateway-eval gateway-quick-eval \
  --gateway-url https://gateway.example.com/v1 \
  --gateway-api-key "..." \
  --model gpt-5.5 \
  --official-url https://api.openai.com/v1 \
  --official-api-key-env OPENAI_API_KEY
```

### Out-of-band leakage (honeytokens)

To detect whether a gateway forwards your data somewhere it shouldn't, pass a webhook/canary base
URL. The run embeds a unique URL honeytoken in one security probe:

```bash
uv run llm-gateway-eval gateway-quick-eval \
  --gateway-url https://gateway.example.com/v1 \
  --gateway-api-key "..." \
  --model gpt-5.5 \
  --honeytoken-base-url https://webhook.example/hook
```

After exporting events from your webhook/canary service, import them back into the run to update
the summary and re-render the report:

```bash
uv run llm-gateway-eval honeytoken-events runs/gateway-quick-eval \
  --events webhook-events.jsonl \
  --report-out reports/gateway-quick-eval.md
```

> If a single run includes both official and gateway targets, a webhook hit proves out-of-band
> exposure but not which target caused it. Use a gateway-only run, or separate official/gateway
> runs, when you need attribution.

### Full YAML workflow

For repeatable, config-driven evaluations, drive `validate` → `run` → `report` with a YAML config.
The example configs reference the `LLM_GATEWAY_API_KEY` and `OPENAI_API_KEY` environment variables:

```bash
export LLM_GATEWAY_API_KEY="..."
export OPENAI_API_KEY="..."

uv run llm-gateway-eval validate \
  --config configs/eval.example.yaml \
  --cases data/cases/smoke.jsonl

uv run llm-gateway-eval run \
  --config configs/eval.example.yaml \
  --cases data/cases/smoke.jsonl \
  --out runs/smoke

uv run llm-gateway-eval report runs/smoke --out reports/smoke.md
```

A focused, security-leaning suite is also bundled. Audit transport first, then run the core cases:

```bash
uv run llm-gateway-eval audit --config configs/eval.gateway-core.yaml --online-tls

uv run llm-gateway-eval run \
  --config configs/eval.gateway-core.yaml \
  --cases data/cases/gateway_core.jsonl \
  --out runs/gateway-core

uv run llm-gateway-eval report runs/gateway-core --out reports/gateway-core.md
```

### Codex and coding-agent comparison

Beyond API cases, you can compare how a real coding agent behaves on the official model versus the
same model routed through a gateway.

Compare your current official Codex config against a gateway with just a URL and key:

```bash
uv run llm-gateway-eval codex-quick-compare \
  --gateway-url https://gateway.example.com/v1 \
  --gateway-api-key "..." \
  --model gpt-5.5 \
  --gateway-price-multiplier 0.8
```

For an exact cost comparison, pass per-1M-token gateway prices instead of a multiplier:

```bash
uv run llm-gateway-eval codex-quick-compare \
  --gateway-url https://gateway.example.com/v1 \
  --gateway-api-key "..." \
  --model gpt-5.5 \
  --gateway-input-price 4.00 \
  --gateway-cached-input-price 0.40 \
  --gateway-output-price 24.00
```

To compare subscription-backed coding agents directly, run the same executable tasks with your
locally authenticated `codex` and `claude` CLIs (no API keys required):

```bash
uv run llm-gateway-eval agent-compare \
  --codex-model gpt-5.5 \
  --claude-model sonnet \
  --cctrace \
  --repeats 3
```

With `--cctrace`, each run also stores a local trace session under its workspace. Claude Code can
also be routed through an Anthropic Messages-compatible gateway:

```bash
uv run llm-gateway-eval agent-compare \
  --no-codex \
  --claude-gateway-url https://gateway.example.com \
  --claude-gateway-api-key "..." \
  --claude-model claude-sonnet-4-6
```

For named, profile-based Codex comparisons (profiles defined in your Codex config), set whatever
environment variable your gateway profile references:

```bash
GATEWAY_API_KEY=... uv run llm-gateway-eval codex-compare \
  --tasks data/codex_tasks \
  --official-profile official \
  --gateway-profile gateway \
  --repeats 3 \
  --out runs/codex-gateway \
  --report-out reports/codex-gateway.md
```

See [docs/agent-compare.md](docs/agent-compare.md) and [docs/codex-compare.md](docs/codex-compare.md)
for agent and profile setup details.

### Website task benchmark

For a more realistic quality check, use a small static website as the task and ask both official
Codex and gateway-routed Codex to implement the exact same prompt. Each task directory contains:

- `TASK.md`: the prompt given to Codex.
- `repo/`: the starter project.
- `repo/verify.sh`: deterministic acceptance checks.

```bash
export GATEWAY_API_KEY="..."

uv run llm-gateway-eval codex-quick-compare \
  --gateway-url https://gateway.example.com/v1 \
  --gateway-api-key-env GATEWAY_API_KEY \
  --model gpt-5.5 \
  --wire-api responses \
  --tasks data/website_tasks_blog \
  --repeats 1 \
  --timeout-seconds 720 \
  --out runs/personal-blog-compare \
  --report-out reports/personal-blog-compare.md
```

Interpret task results in two layers:

- **Functional quality:** did `verify.sh` pass, and does the generated UI satisfy the task prompt?
- **Agent stability and efficiency:** did Codex exit cleanly, how long did it take, and how many input/output/reasoning tokens were consumed?

This distinction matters because a run can produce a valid website but still time out during extra
self-checking. Keep screenshots and raw `results.jsonl` as local evidence under `reports/` and
`runs/`; do not commit them unless you intentionally want to publish the evidence.

## What It Measures

- Model authenticity: response model metadata mismatch, direct-baseline comparison readiness, and high-confidence capability probes tagged `model_authenticity`.
- Transport safety: `audit` checks HTTPS usage, TLS hostname verification, certificate expiry, and obvious static-secret headers.
- Privacy leakage: security/privacy cases, optional external honeytoken event imports, plus default redaction for API keys, bearer tokens, JWTs, emails, and common secret assignments in result/report output.
- Stability: repeated case runs, retry attempts, P50/P95/P99 latency, network error counts, HTTP/model invocation error counts, and request success rate.
- Quality: assertion pass rate by case, category, and provider.
- Reliability: request success rate, errors, and failed assertions.
- Performance: latency P50/P95/P99, output tokens per second.
- Cost and usage accuracy: estimated input/output token cost by provider, usage completeness, total-token consistency, and paired token deltas versus official baseline.
- Routing/degradation: model metadata variants, official-vs-gateway quality gaps, repeated-case input-token variation, pass/fail flaps, and temperature-0 output drift.
- Compatibility: JSON schema success rate, usage availability, streaming field placeholders.
- Safety/security coverage: pass rate for cases tagged or categorized as `safety`, `security`, or `privacy`.

## Case Format

Each JSONL line is an `EvalCase`:

```json
{"id":"json_intent","category":"compatibility","messages":[{"role":"user","content":"Only return JSON: {\"intent\":\"billing\"}"}],"assertions":[{"type":"json_schema","schema":{"type":"object","required":["intent"],"properties":{"intent":{"const":"billing"}}}}],"tags":["json"]}
```

Supported assertion types:

- `contains`
- `not_contains`
- `equals`
- `regex`
- `json_schema`
- `refusal_expected`

## Project Layout

```
src/llm_gateway_eval/   CLI, OpenAI-compatible client, assertions, metrics, pricing,
                        security probes, Codex/Claude agent comparison, and reporting
configs/                example YAML configs (generic + gateway-core)
data/cases/             JSONL API eval cases
data/codex_tasks/       executable coding-agent tasks
data/website_tasks_*/   static-website benchmark tasks
templates/              Markdown report templates
docs/                   methodology and setup notes
tests/                  unit and integration smoke tests
```

Generated artifacts such as `runs/`, `reports/`, caches, and virtual environments are intentionally
ignored by git. Treat those folders as local evidence, not source.

A bundled Codex skill for the end-to-end workflow lives in `llm-gateway-eval-report/`; copy or
symlink it into `~/.codex/skills/` to install it locally.

## Notes & Limitations

- Prefer API keys through environment variables (`--gateway-api-key-env`, config `api_key_env`). Avoid committing raw keys or passing them in shell history.
- Results and reports store redacted outputs; assertions run against the original provider response before redaction.
- Local run artifacts can still contain prompts, generated code, model outputs, endpoint names, latency, usage, and pricing evidence. Review or redact before sharing.
- `runs/` and `reports/` are ignored by default so sensitive local evidence does not get committed accidentally.
- Model authenticity probes detect suspicious mismatches and regressions. They are anomaly detection, not cryptographic proof that a provider is serving a specific model.
- The first version targets OpenAI-compatible Chat Completions (`/chat/completions`).
- Ragas, promptfoo red teaming, k6/Locust, OpenTelemetry, and Langfuse are intentionally left as future extension points.

See [docs/evaluation-methodology.md](docs/evaluation-methodology.md) for the recommended interpretation.

## License

Released under the [MIT License](LICENSE).
