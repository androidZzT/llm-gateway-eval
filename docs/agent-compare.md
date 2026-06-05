# Coding Agent Comparison

Use this workflow when you want to evaluate Codex and Claude Code through their local CLI subscriptions instead of direct model APIs.

## What It Measures

The runner gives each agent the same task repo and prompt, then runs the task verifier:

```text
task-id/
  TASK.md
  repo/
    verify.sh
    ...
```

Each run gets an isolated workspace under `runs/coding-agents/workspaces/`. The report compares:

- executable pass rate
- agent CLI/runtime failures
- verifier failures
- changed files and patch diffs
- duration
- token usage when the CLI emits usage JSON
- optional API-equivalent cost if you pass token prices

## Run Codex And Claude Code

Make sure both CLIs are logged in locally:

```bash
codex login
claude auth
```

Then run:

```bash
uv run llm-gateway-eval agent-compare \
  --tasks data/codex_tasks \
  --codex-model gpt-5.5 \
  --claude-model sonnet \
  --cctrace \
  --repeats 3 \
  --out runs/coding-agents \
  --report-out reports/coding-agents.md
```

The default command templates are:

```bash
codex exec --json --sandbox workspace-write -c 'approval_policy="never"' -c 'web_search="disabled"' "{prompt}"
claude --print --permission-mode bypassPermissions --output-format stream-json --no-session-persistence "{prompt}"
```

The task workspaces are throwaway copies of `repo/`, so bypass/auto-edit modes are intended to be used only inside those isolated directories.

## cctrace Evidence

Add `--cctrace` to wrap each agent invocation:

```bash
uv run llm-gateway-eval agent-compare \
  --tasks data/codex_tasks \
  --codex-model gpt-5.5 \
  --claude-model sonnet \
  --cctrace
```

Each task run stores its trace next to the patch:

```text
runs/coding-agents/workspaces/<target>/<task>/run-<n>/
  patch.diff
  agent-stdout.jsonl
  agent-stderr.txt
  cctrace-session/
    session.json
    events.jsonl
```

The report includes a `cctrace Evidence` table with the session path and event count. To replay one trace in the cctrace UI, point cctrace at the captured session id if the session is still in its original store, or import the `cctrace-session/` folder in the cctrace UI.

Implementation note: the runner gives every wrapped subprocess its own `TMPDIR`, so cctrace writes into the task workspace first and the stable `cctrace-session/` folder is copied from there.

## Run Only One Agent

```bash
uv run llm-gateway-eval agent-compare --no-claude
uv run llm-gateway-eval agent-compare --no-codex
```

## Route Claude Code Through A Gateway

Claude Code gateway mode expects an Anthropic Messages compatible gateway, not an OpenAI-compatible `/chat/completions` endpoint. The gateway should support `/v1/messages` and `/v1/messages/count_tokens`.

```bash
uv run llm-gateway-eval agent-compare \
  --no-codex \
  --claude-gateway-url https://gateway.example.com \
  --claude-gateway-api-key "..." \
  --claude-model claude-sonnet-4-6 \
  --repeats 3
```

For shared shells, keep the key in an environment variable:

```bash
export CLAUDE_GATEWAY_API_KEY="..."

uv run llm-gateway-eval agent-compare \
  --no-codex \
  --claude-gateway-url https://gateway.example.com \
  --claude-gateway-api-key-env CLAUDE_GATEWAY_API_KEY \
  --claude-model claude-sonnet-4-6
```

By default the runner injects:

```bash
ANTHROPIC_BASE_URL=https://gateway.example.com
ANTHROPIC_AUTH_TOKEN=...
```

Use `--claude-gateway-auth api-key` if your gateway expects `ANTHROPIC_API_KEY` / `X-Api-Key` instead of bearer auth. Use `--claude-gateway-model-discovery` when the gateway implements `/v1/models` and you want Claude Code to discover gateway model names.

## Optional Cost Estimates

Subscription usage is not the same as API billing. If you still want an API-equivalent cost estimate from emitted token usage, pass per-1M token prices:

```bash
uv run llm-gateway-eval agent-compare \
  --codex-input-price 5 \
  --codex-cached-input-price 0.5 \
  --codex-output-price 30 \
  --claude-input-price 3 \
  --claude-cached-input-price 0.3 \
  --claude-output-price 15
```

## Interpretation

Use this as a coding quality and agent reliability benchmark. It is not a replacement for API-level gateway evaluation because subscription CLIs do not always expose stable model metadata, transport details, or exact billing semantics.

For gateway authenticity with Codex specifically, continue to use `codex-quick-compare`, because it compares the same Codex shell against official and gateway provider configurations.
