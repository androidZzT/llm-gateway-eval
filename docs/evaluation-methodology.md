# Gateway Evaluation Methodology

This project treats a large-model gateway as production infrastructure, not just a model endpoint.

## 1. Is the Model Real?

There is no single prompt that can prove model identity. The practical evaluation is anomaly detection:

- Compare the gateway against a direct provider baseline with the same requested model and decoding params.
- Track `requested_model` versus response `model`; mismatches are evidence that needs explanation.
- Run capability probes tagged `model_authenticity`: reasoning, coding, JSON/schema following, and long-context sentinel lookup.
- Repeat probes over time. A real gateway should be stable under deterministic settings; sudden quality or metadata shifts are suspect.

Evidence to include in a report:

- Model name mismatch count.
- Model-authenticity case pass rate.
- Output deltas versus direct baseline for the same cases.
- Any provider documentation or contract that maps gateway aliases to upstream models.

For the lowest-friction first pass:

```bash
uv run llm-gateway-eval gateway-quick-eval \
  --gateway-url https://gateway.example.com/v1 \
  --gateway-api-key "..." \
  --model gpt-5.5
```

This runs model-authenticity probes against the gateway only. It can catch suspicious regressions, metadata mismatches, JSON/schema weakness, and obvious capability gaps, but it does not prove the upstream model.

For stronger evidence, add the direct provider baseline:

```bash
export OPENAI_API_KEY="..."

uv run llm-gateway-eval gateway-quick-eval \
  --gateway-url https://gateway.example.com/v1 \
  --gateway-api-key "..." \
  --model gpt-5.5 \
  --official-url https://api.openai.com/v1 \
  --official-api-key-env OPENAI_API_KEY
```

This produces one report with `official` and `gateway` providers side by side. For coding-agent quality specifically, use `codex-quick-compare`, because executable task verification is a better signal than comparing generated text directly.

## 2. Is Data Transmission Safe?

The minimum bar is HTTPS with certificate and hostname verification. The CLI client uses `httpx` defaults, which verify TLS certificates unless the code is changed.

Use:

```bash
uv run llm-gateway-eval audit --config configs/eval.gateway-core.yaml --online-tls
```

The quick command runs the same audit automatically and stores it in `runs/gateway-quick-eval/audit.json`.

The audit checks:

- Non-local endpoints use HTTPS.
- TLS handshake and hostname verification succeed.
- Certificate expiry is acceptable.
- DNS resolution evidence and private/local address warnings.
- Leaf certificate SHA-256 fingerprint, subject, and issuer.
- API keys are referenced through environment variables.
- Config does not hard-code obvious credential headers.

This reduces MITM risk, but it does not replace a full vendor security review. For production, also require data retention terms, logging policy, access controls, audit logs, and incident response terms.

## 2.1. Is The Gateway Tampering With Requests?

The gateway is a legitimate TLS endpoint, so a black-box client cannot prove it never adds hidden prompts or modifies payloads. The practical approach is to collect anomaly evidence.

`gateway-quick-eval` now adds dynamic security probes by default:

- fake API key canary that must not be repeated
- fake email canary that must not be repeated
- system-integrity token that must be returned exactly
- hidden-instruction JSON probe
- optional external URL honeytoken for egress monitoring

It writes:

```text
runs/gateway-quick-eval/security_probes.json
summary.security_analysis
```

When an official baseline is configured, the summary also compares input token counts per case/repeat. If the gateway input token count is much higher than the official baseline, the report flags a usage anomaly. That is not proof of tampering by itself, but it is a strong lead for hidden prompt, routing wrapper, or provider-side preprocessing.

For out-of-band privacy leakage, add a webhook/canary URL:

```bash
uv run llm-gateway-eval gateway-quick-eval \
  --gateway-url https://gateway.example.com/v1 \
  --gateway-api-key "..." \
  --model gpt-5.5 \
  --honeytoken-base-url https://webhook.example/hook
```

This adds one probe containing a unique URL and asks the model not to request or repeat it. The CLI still checks output-side leakage with `not_contains`; your webhook or canary service checks whether the URL was requested out of band by a gateway, scanner, log pipeline, or another intermediary.

After exporting events from the webhook/honeytoken service, import them:

```bash
uv run llm-gateway-eval honeytoken-events runs/gateway-quick-eval \
  --events webhook-events.jsonl \
  --report-out reports/gateway-quick-eval.md
```

The command scans JSON, JSONL, or plain-text event exports for the generated honeytoken values, writes `honeytoken_events.json`, updates `summary.security_analysis`, and redacts the actual URL in report excerpts. If official and gateway targets were tested in the same run, a hit proves exposure but not attribution. Use gateway-only runs or separate official/gateway runs when attribution matters.

## 3. Will It Be Stable?

Stability needs repeated requests, not one successful smoke call.

Use `repeat_per_case` to run each case multiple times and `attempts` to test retry behavior. The summary separates:

- `network_error_count`: timeout, TLS, and connection failures.
- `model_invocation_error_count`: 429, 4xx, 5xx, and malformed model responses.
- P50/P95/P99 latency and tokens per second.
- Request success rate and assertion pass rate.

For a procurement or launch report, run the same suite at several times of day and include both raw `results.jsonl` and rendered `reports/*.md`.

## 4. Is Usage and Billing Trustworthy?

`summary.usage_billing_analysis` checks what can be verified from OpenAI-compatible responses:

- Whether usage fields are present for every result.
- Whether `input_tokens + output_tokens` is consistent with `total_tokens`.
- Whether gateway token counts diverge from the official baseline on the same case and repeat.
- Whether reported usage is wildly far from a rough local token estimate.

The strongest signal is a large input-token delta versus official direct baseline, because the prompt is the same. Output and total deltas can be caused by legitimate response differences, so they are medium-confidence billing signals.

This still does not prove final charges. For production procurement, reconcile these response-level estimates against the gateway account ledger, balance changes, invoice exports, and failed-request charging policy.

## 5. Is Routing or Degradation Happening?

`summary.routing_degradation_analysis` collects black-box signals that suggest hidden routing, fallback, or quality degradation:

- response `model` values changing across runs for the same requested model
- response `model` differing from `requested_model`
- official baseline passes a case substantially more often than the gateway
- the same provider/case alternates between pass and fail across repeats
- the same provider/case has large input-token variation across repeats
- temperature-0 repeats produce different normalized outputs
- model-authenticity probes fail on the gateway

These are anomaly signals, not proof of an internal routing decision. The best evidence comes from repeated deterministic runs, an official direct baseline, and a written gateway contract that maps aliases to upstream models and declares fallback behavior.

## 6. Where cctrace Helps

`cctrace` is useful for security analysis at the coding-agent layer. It can preserve process events, transcript events, tool calls, tool results, and API request/response records when ccglass data is available.

Useful signals:

- whether a canary appears in prompts, tool inputs, tool outputs, or final responses
- whether unexpected tools or subagents were invoked
- whether agent behavior changed after a gateway run
- timing alignment between process/network/API events and suspicious outputs
- forensic artifacts to inspect after a failed tamper/privacy probe

It does not replace gateway-side attestation, because a gateway can still modify traffic after the local agent emits a request. But it gives you a strong local evidence trail: what the agent intended to send, what tools it used, and what responses it saw.
