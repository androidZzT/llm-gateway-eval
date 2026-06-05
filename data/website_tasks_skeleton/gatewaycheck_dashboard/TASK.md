Complete the static `GatewayCheck` dashboard.

This is a benchmark task: the exact same prompt will be used for an official Codex baseline and a gateway/proxy Codex target. Keep the implementation concise. Prefer filling TODOs and improving the existing files instead of rewriting everything.

Goal:
- Make the first screen a usable ops dashboard for checking an OpenAI-compatible LLM gateway API.
- The app should look polished, compact, and production-like.

Edit:
- `index.html`
- `styles.css`
- `app.js`

Required:
- No build step, package manager, external CDN, external image, or network call.
- Keep the app static and openable through `index.html`.
- Implement the exported JS functions in `app.js`:
  - `computeSummary(runs)`
  - `filterCases(cases, filters)`
  - `renderDashboard(state)`
  - `formatPercent(value)`
- Keep exposing them via `module.exports` and `window.GatewayCheck`.
- The rendered UI must include API configuration, model, API key env, Run check, search, filters, scorecards, quality, safety/privacy, token usage, latency/stability, error breakdown, test case table, and export action.
- Make the layout responsive and visually polished.

Run `bash ./verify.sh` before finishing.
