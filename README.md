# llm-gateway-eval

`llm-gateway-eval` is a small Python CLI for evaluating OpenAI-compatible LLM gateways against direct-provider baselines.

It runs the same JSONL eval cases against each configured target, captures output quality assertions, latency, token usage, estimated cost, errors, and compatibility signals, then renders a Markdown report.

## Repository Contents

- `src/llm_gateway_eval/`: CLI, OpenAI-compatible client, assertions, metrics, pricing, security probes, Codex/Claude agent comparison, and report rendering.
- `configs/`: example YAML configs for generic and gateway-focused evaluations.
- `data/cases/`: JSONL API evaluation cases.
- `data/codex_tasks/`: executable coding-agent tasks used by Codex/Claude comparisons.
- `data/website_tasks_*`: static website benchmark tasks for comparing official Codex against a gateway-backed Codex route.
- `templates/`: Markdown report templates.
- `docs/`: methodology and setup notes.
- `llm-gateway-eval-report/`: Codex skill for running the end-to-end gateway evaluation workflow and rendering the Chinese HTML report.
- `tests/`: unit and integration smoke tests.

Generated artifacts such as `runs/`, `reports/`, caches, and virtual environments are intentionally ignored by git. Treat those folders as local evidence, not source.

To install the bundled Codex skill locally, copy or symlink `llm-gateway-eval-report/` into `~/.codex/skills/`.

## Quick Start

```bash
git clone https://github.com/<owner>/llm-gateway-eval.git
cd llm-gateway-eval
uv sync
```

If you only want to start evaluating a gateway with the least setup, provide URL, API key, and model:

```bash
uv run llm-gateway-eval gateway-quick-eval \
  --gateway-url https://gateway.example.com/v1 \
  --gateway-api-key "..." \
  --model gpt-5.5
```

This writes:

- `runs/gateway-quick-eval/audit.json`: HTTPS/TLS, key handling, and static-secret checks.
- `runs/gateway-quick-eval/security_probes.json`: per-run canaries and tamper probe definitions.
- `runs/gateway-quick-eval/results.jsonl`: per-case evidence for authenticity, privacy/security, and stability probes.
- `runs/gateway-quick-eval/summary.json`: pass rates, latency, error classes, usage/billing analysis, routing/degradation signals, security analysis, and scores.
- `reports/gateway-quick-eval.md`: human-readable report.

To add out-of-band leakage monitoring, pass a webhook or canary URL. The run will embed a unique URL honeytoken in one security probe:

```bash
uv run llm-gateway-eval gateway-quick-eval \
  --gateway-url https://gateway.example.com/v1 \
  --gateway-api-key "..." \
  --model gpt-5.5 \
  --honeytoken-base-url https://webhook.example/hook
```

After exporting events from your webhook/honeytoken service, import them back into the run:

```bash
uv run llm-gateway-eval honeytoken-events runs/gateway-quick-eval \
  --events webhook-events.jsonl \
  --report-out reports/gateway-quick-eval.md
```

If the same run includes both official and gateway targets, a webhook hit proves out-of-band exposure but not which target caused it. Run gateway-only or separate official/gateway runs when you need attribution.

For a direct-provider baseline in the same run, add:

```bash
export OPENAI_API_KEY="..."

uv run llm-gateway-eval gateway-quick-eval \
  --gateway-url https://gateway.example.com/v1 \
  --gateway-api-key "..." \
  --model gpt-5.5 \
  --official-url https://api.openai.com/v1 \
  --official-api-key-env OPENAI_API_KEY
```

For the full YAML-driven workflow:

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

For the core gateway evaluation you described, use the focused suite:

```bash
uv run llm-gateway-eval audit --config configs/eval.gateway-core.yaml --online-tls

uv run llm-gateway-eval run \
  --config configs/eval.gateway-core.yaml \
  --cases data/cases/gateway_core.jsonl \
  --out runs/gateway-core

uv run llm-gateway-eval report runs/gateway-core --out reports/gateway-core.md
```

To compare Codex with the official model versus Codex through a gateway:

```bash
uv run llm-gateway-eval codex-quick-compare \
  --gateway-url https://gateway.example.com/v1 \
  --gateway-api-key "..." \
  --model gpt-5.5 \
  --gateway-price-multiplier 0.8
```

To compare subscription-backed coding agents directly, run the same executable tasks with local Codex and Claude Code:

```bash
uv run llm-gateway-eval agent-compare \
  --codex-model gpt-5.5 \
  --claude-model sonnet \
  --cctrace \
  --repeats 3
```

This uses your locally authenticated `codex` and `claude` CLIs. It does not require official API keys.
With `--cctrace`, each run also stores a local trace session under its workspace.
See [docs/agent-compare.md](docs/agent-compare.md) for details.

Claude Code can also be routed through an Anthropic Messages compatible gateway:

```bash
uv run llm-gateway-eval agent-compare \
  --no-codex \
  --claude-gateway-url https://gateway.example.com \
  --claude-gateway-api-key "..." \
  --claude-model claude-sonnet-4-6
```

For exact gateway prices, pass per-1M token rates:

```bash
uv run llm-gateway-eval codex-quick-compare \
  --gateway-url https://gateway.example.com/v1 \
  --gateway-api-key "..." \
  --model gpt-5.5 \
  --gateway-input-price 4.00 \
  --gateway-cached-input-price 0.40 \
  --gateway-output-price 24.00
```

To compare all WeyToken model prices against the official catalog:

```bash
uv run llm-gateway-eval weytoken-pricing \
  --base-url https://api.weytoken.com \
  --group best
```

This writes JSON/CSV/Markdown outputs plus a missing-official template for models that need official prices filled in.

For named Codex profiles:

```bash
GATEWAY_API_KEY=... uv run llm-gateway-eval codex-compare \
  --tasks data/codex_tasks \
  --official-profile official \
  --gateway-profile gateway \
  --repeats 3 \
  --out runs/codex-gateway \
  --report-out reports/codex-gateway.md
```

See [docs/codex-compare.md](docs/codex-compare.md) for profile setup and task format.

## Website Task Benchmark

For a more realistic quality check, use a small static website as the task and ask both official Codex and gateway-routed Codex to implement the exact same prompt. Each task directory contains:

- `TASK.md`: the prompt given to Codex.
- `repo/`: the starter project.
- `repo/verify.sh`: deterministic acceptance checks.

Example:

```bash
export WEYTOKEN_API_KEY="..."

uv run llm-gateway-eval codex-quick-compare \
  --gateway-url https://api.weytoken.com/v1 \
  --gateway-api-key-env WEYTOKEN_API_KEY \
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

This distinction matters because a run can produce a valid website but still time out during extra self-checking. Keep screenshots and raw `results.jsonl` as local evidence under `reports/` and `runs/`; do not commit them unless you intentionally want to publish the evidence.

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

## Notes

- Prefer API keys through environment variables (`--gateway-api-key-env`, config `api_key_env`). Avoid committing raw keys or passing them in shell history.
- Results and reports store redacted outputs; assertions run against the original provider response before redaction.
- Local run artifacts can still contain prompts, generated code, model outputs, endpoint names, latency, usage, and pricing evidence. Review or redact before sharing.
- `runs/` and `reports/` are ignored by default so sensitive local evidence does not get committed accidentally.
- Model authenticity probes detect suspicious mismatches and regressions. They are not cryptographic proof that a provider is serving a specific model.
- The first version targets OpenAI-compatible Chat Completions (`/chat/completions`).
- Ragas, promptfoo red teaming, k6/Locust, OpenTelemetry, and Langfuse are intentionally left as future extension points.

See [docs/evaluation-methodology.md](docs/evaluation-methodology.md) for the recommended interpretation.
