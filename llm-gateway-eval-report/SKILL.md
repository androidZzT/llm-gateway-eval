---
name: llm-gateway-eval-report
description: Run an end-to-end LLM gateway evaluation and generate a Chinese HTML report. Use when the user wants to evaluate an OpenAI-compatible or Codex-compatible model gateway/proxy/中转站, compare it with an official Codex/API baseline, check model authenticity, security/privacy, token usage, cost, performance, stability, or produce a polished Chinese HTML evaluation report from llm-gateway-eval run artifacts.
---

# LLM Gateway Eval Report

## Goal

Evaluate an LLM gateway with minimal user configuration, then produce a Chinese HTML report covering:

1. 测试任务是什么
2. 任务完成质量
3. 安全评测
4. Token 消耗
5. 性能和稳定性

Use the local `llm-gateway-eval` project and this skill's report renderer.

## Required Inputs

Collect only what is necessary:

- `gateway_url`: gateway base URL. Prefer `/v1` for Codex/OpenAI-compatible Responses API.
- `model`: requested model name.
- `api_key`: either a raw key or an environment variable name. Prefer an environment variable.

Default assumptions when the user does not specify:

- Official baseline: current Codex subscription/config.
- Gateway key env var: `GATEWAY_API_KEY`.
- Codex wire API: `responses`.
- Coding repeats: `2`.
- Security repeats: `2`.
- Project root: current working directory if it contains `pyproject.toml` and `src/llm_gateway_eval`; otherwise ask the user for the local checkout path.

## Safety Rules

- Never write API keys into configs, reports, shell history, or command-line arguments when avoidable.
- Prefer `--gateway-api-key-env ENV_NAME`.
- If the user gives a raw key, set it only in the current process environment and do not print it.
- Do not use `curl -H "Authorization: Bearer ..."` with the key directly in the command line.
- Flag any non-local `http://` gateway URL as a transport security failure.
- Treat black-box model-authenticity probes as evidence, not proof.

## Workflow

### 1. Prepare

Resolve the project root and verify the CLI:

```bash
cd <project-root>
uv run llm-gateway-eval --help
```

If the user supplies `http://host:port/`, test whether the working base URL should be `http://host:port/v1`. Prefer the `/v1` URL for Codex quick compare unless the user explicitly says otherwise.

Use a stable run slug such as:

```text
<model>-gateway-eval-YYYYMMDD-HHMM
```

### 2. Run Codex Official vs Gateway Coding Eval

Use current Codex config as the official baseline and temporary gateway overrides for the gateway target:

```bash
uv run llm-gateway-eval codex-quick-compare \
  --gateway-url "<gateway_url>" \
  --gateway-api-key-env "<api_key_env>" \
  --model "<model>" \
  --wire-api responses \
  --repeats 2 \
  --timeout-seconds 900 \
  --out "runs/<slug>-codex" \
  --report-out "reports/<slug>-codex.md"
```

This produces:

- `runs/<slug>-codex/results.jsonl`
- `runs/<slug>-codex/summary.json`
- `reports/<slug>-codex.md`

### 3. Run Gateway Security and Stability Quick Eval

Run the API-level quick eval:

```bash
uv run llm-gateway-eval gateway-quick-eval \
  --gateway-url "<gateway_url>" \
  --gateway-api-key-env "<api_key_env>" \
  --model "<model>" \
  --repeats 2 \
  --attempts 2 \
  --concurrency 2 \
  --timeout-seconds 120 \
  --out "runs/<slug>-security" \
  --report-out "reports/<slug>-security.md"
```

This covers transport audit, privacy/security cases, dynamic canary probes, tamper probes, usage completeness, JSON schema compatibility, and stability repeats.

If the user provides an external honeytoken/webhook URL, add `--honeytoken-base-url "<url>"`, then after the run import event records:

```bash
uv run llm-gateway-eval honeytoken-events \
  "runs/<slug>-security" \
  --events "<events.jsonl>"
```

### 4. Generate Chinese HTML Report

Optionally prepare authoritative benchmark reuse before rendering. This does not run heavy external harnesses by itself; it creates a plan and imports task-level outputs when available:

```bash
uv run llm-gateway-eval benchmark-plan \
  --suite "terminal-bench,swe-bench-verified,bfcl" \
  --sample-size 20 \
  --difficulty smoke \
  --out "runs/<slug>-benchmark-plan.json"
```

After an external benchmark runner produces JSON/JSONL/CSV results, normalize them:

```bash
uv run llm-gateway-eval benchmark-import \
  --input "<official-results.jsonl>" \
  --benchmark terminal-bench \
  --target official \
  --out "runs/<slug>-benchmarks/summary.json"

uv run llm-gateway-eval benchmark-import \
  --input "<gateway-results.jsonl>" \
  --benchmark terminal-bench \
  --target gateway \
  --append \
  --out "runs/<slug>-benchmarks/summary.json"
```

Use the bundled renderer:

```bash
python "<skill-dir>/scripts/render_gateway_eval_report.py" \
  --coding-run "runs/<slug>-codex" \
  --security-run "runs/<slug>-security" \
  --benchmark-run "runs/<slug>-benchmark-plan.json" \
  --gateway-url "<gateway_url>" \
  --model "<model>" \
  --out "reports/<slug>-complete.html"
```

The script reads `summary.json`, `results.jsonl`, `audit.json`, and optional quick eval artifacts.
If imported benchmark results exist, pass `--benchmark-run "runs/<slug>-benchmarks/summary.json"` instead of the plan file.

See `references/report-schema.md` if the renderer needs adjustment for changed artifact schemas.

### 5. Verify and Summarize

Validate that the HTML exists and contains all required sections:

```bash
python - <<'PY'
from html.parser import HTMLParser
from pathlib import Path
path = Path("reports/<slug>-complete.html")
text = path.read_text(encoding="utf-8")
HTMLParser().feed(text)
required = ["测试任务是什么", "任务完成质量", "安全评测", "Token 消耗", "性能和稳定性"]
missing = [item for item in required if item not in text]
print({"html_ok": not missing, "missing": missing, "bytes": len(text.encode("utf-8"))})
PY
```

Optional interactive web workspace:

```bash
uv run llm-gateway-eval web-report \
  --coding-run "runs/<slug>-codex" \
  --security-run "runs/<slug>-security" \
  --benchmark-run "runs/<slug>-benchmark-plan.json" \
  --gateway-url "<gateway_url>" \
  --model "<model>" \
  --out "reports/<slug>-studio.html"
```

Use this when the user wants to inspect whether the real evaluation functionality and UI are correct. It renders a static local HTML app with tabs for 总览、任务质量、安全、Token、性能、Benchmark、明细.

Optional local evaluation website:

```bash
uv run llm-gateway-eval serve \
  --host 127.0.0.1 \
  --port 8787
```

Use this when the user wants a website where they can enter `gateway_url`, `model`, and an API key or API-key environment variable, then run a real OpenAI-compatible gateway quality evaluation from the browser. The website posts configs to the local server, keeps raw API keys in process memory only, writes redacted artifacts under `runs/web-gateway-eval/`, and renders quality, safety, token, stability, and error results in the page.

Final response should include:

- HTML report path as a clickable absolute file link.
- One-paragraph verdict.
- Key numbers: coding pass rate, security request success rate, transport audit status, token delta, latency/stability issues.
- Any tests or validation run.

## Interpretation Checklist

Model authenticity:

- Compare paired coding task pass rates.
- Check model-authenticity probes and model name mismatch events.
- Mention that black-box evidence is not cryptographic proof.

Security:

- Transport scheme and TLS status matter most.
- Canary/tamper probes only detect suspicious output-side behavior.
- External honeytoken monitoring is required for out-of-band leakage detection.

Token and cost:

- Compare input, cached input, output, reasoning, and total tokens.
- If gateway pricing is missing, say cost delta is unavailable.
- If baseline is a subscription account, describe official cost as API-equivalent, not actual subscription billing.

Performance and stability:

- Separate Codex end-to-end coding duration from API quick eval latency.
- Highlight HTTP 4xx/5xx, stream disconnects, `auth_unavailable`, missing usage, and pass/fail flapping.
