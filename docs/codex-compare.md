# Codex Official vs Gateway Comparison

This workflow evaluates whether a gateway behaves like the claimed official model when both are used through Codex.

## Profiles

Create two user-level Codex profiles. Provider settings belong in user-level config/profile files, not project `.codex/config.toml`.

`~/.codex/official.config.toml`:

```toml
model = "gpt-5.5"
sandbox_mode = "workspace-write"
approval_policy = "never"
web_search = "disabled"
```

`~/.codex/gateway.config.toml`:

```toml
model = "gpt-5.5"
model_provider = "gateway"
sandbox_mode = "workspace-write"
approval_policy = "never"
web_search = "disabled"

[model_providers.gateway]
name = "Gateway under test"
base_url = "https://gateway.example.com/v1"
wire_api = "responses"
env_key = "GATEWAY_API_KEY"
```

## Task Shape

Each task is a directory with:

```text
task-id/
  TASK.md
  repo/
    verify.sh
    ...
```

The runner copies `repo/` into isolated workspaces, initializes a git baseline if needed, runs `codex exec`, runs `bash ./verify.sh`, then captures `patch.diff`, `codex-events.jsonl`, verifier logs, `results.jsonl`, and `summary.json`.

## Run

Minimal setup: use your current Codex official configuration as the baseline and provide only the gateway URL/key:

```bash
uv run llm-gateway-eval codex-quick-compare \
  --gateway-url https://gateway.example.com/v1 \
  --gateway-api-key "..." \
  --model gpt-5.5
```

For shared shells, avoid putting the key in shell history:

```bash
export GATEWAY_API_KEY=...
uv run llm-gateway-eval codex-quick-compare \
  --gateway-url https://gateway.example.com/v1 \
  --gateway-api-key-env GATEWAY_API_KEY \
  --model gpt-5.5
```

The quick command does not write gateway credentials to `~/.codex`; it injects a temporary Codex provider with `-c model_providers...` overrides for the gateway run.

## Pricing

The quick command has a small built-in [OpenAI API pricing](https://openai.com/api/pricing/) snapshot for `gpt-5.5`, `gpt-5.4`, and `gpt-5.4-mini` checked on 2026-06-02. Override prices when OpenAI pricing changes or when you use Batch, Flex, Priority, regional processing, or a different model.

If the gateway quotes a simple discount or markup against official pricing:

```bash
uv run llm-gateway-eval codex-quick-compare \
  --gateway-url https://gateway.example.com/v1 \
  --gateway-api-key-env GATEWAY_API_KEY \
  --model gpt-5.4-mini \
  --gateway-price-multiplier 0.8
```

If the gateway quotes exact token prices, pass per-1M token rates:

```bash
uv run llm-gateway-eval codex-quick-compare \
  --gateway-url https://gateway.example.com/v1 \
  --gateway-api-key-env GATEWAY_API_KEY \
  --model gpt-5.4-mini \
  --gateway-input-price 0.60 \
  --gateway-cached-input-price 0.06 \
  --gateway-output-price 3.60
```

For models outside the built-in snapshot, provide official prices too:

```bash
uv run llm-gateway-eval codex-quick-compare \
  --gateway-url https://gateway.example.com/v1 \
  --gateway-api-key-env GATEWAY_API_KEY \
  --model custom-model \
  --official-input-price 1.00 \
  --official-cached-input-price 0.10 \
  --official-output-price 5.00 \
  --gateway-input-price 0.90 \
  --gateway-cached-input-price 0.09 \
  --gateway-output-price 4.50
```

The report compares estimated cost from actual Codex JSONL token usage:

- total official estimated cost
- total gateway estimated cost
- absolute delta
- percentage delta
- gateway / official ratio
- cost per passed task

## WeyToken Full Price Table

WeyToken exposes its model price table at `/api/pricing`. Generate a full comparison table:

```bash
uv run llm-gateway-eval weytoken-pricing \
  --base-url https://api.weytoken.com \
  --group best
```

Outputs:

- `runs/weytoken-pricing.json`
- `runs/weytoken-pricing.csv`
- `reports/weytoken-pricing.md`
- `runs/weytoken-missing-official.csv`

The built-in official catalog covers OpenAI Codex-oriented models. For all non-OpenAI or custom WeyToken aliases, fill `runs/weytoken-missing-official.csv` with official prices and rerun:

```bash
uv run llm-gateway-eval weytoken-pricing \
  --base-url https://api.weytoken.com \
  --group best \
  --official-prices runs/weytoken-missing-official.csv
```

You can also start from [data/pricing/official_prices.example.csv](../data/pricing/official_prices.example.csv).

Profile-based setup:

```bash
GATEWAY_API_KEY=... uv run llm-gateway-eval codex-compare \
  --tasks data/codex_tasks \
  --official-profile official \
  --gateway-profile gateway \
  --repeats 3 \
  --out runs/codex-gateway \
  --report-out reports/codex-gateway.md
```

## Interpretation

Use paired pass rates rather than text similarity:

- `codex_failures`: Codex/API/runtime failures.
- `verify_failures`: Codex produced a patch, but tests failed.
- `paired_task_deltas`: per-task official-vs-gateway pass-rate gaps.
- Each run workspace contains forensic artifacts for manual inspection.
