Implement a polished static website dashboard named `GatewayCheck`.

This is a benchmark task: the exact same prompt will be used for an official Codex baseline and a gateway/proxy Codex target. Keep the implementation focused and finish by running `bash ./verify.sh`.

Build a single-page operational dashboard for checking an OpenAI-compatible LLM gateway API. It should be usable on the first screen, not a marketing page.

Edit only:
- `index.html`
- `styles.css`
- `app.js`

Requirements:
- Pure static website. No package manager, no build step, no external network resources.
- Include visible controls for gateway URL, model, API key env, a Run check button, a search box, status filter, and provider filter.
- Include visible sections for scorecards, quality, safety/privacy, token usage, latency/stability, error breakdown, and a test case table.
- Use the provided sample data in `app.js`.
- Implement real interaction: filtering test cases by query/status/provider, selecting a row to update details, and recomputing summary metrics from sample runs.
- UI should feel like a compact SaaS/ops tool: tidy, scan-friendly, balanced color palette, stable card/table dimensions, responsive layout.

Required JS exports for `verify.mjs`:
- `computeSummary(runs)`
- `filterCases(cases, filters)`
- `renderDashboard(state)`
- `formatPercent(value)`

Expose the functions through both `module.exports` and `window.GatewayCheck` when available.

Run `bash ./verify.sh` before finishing.
