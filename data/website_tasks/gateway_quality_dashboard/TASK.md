Build a polished static website for evaluating an LLM gateway API.

The same prompt will be used for two Codex targets: an official baseline and a gateway/proxy target. Your job is to implement the website in this repository so `bash ./verify.sh` passes.

Product brief:
- Build a first-screen usable product dashboard, not a marketing landing page.
- The product is named `LLM Gateway Quality Lab`.
- The audience is an engineer or technical operator comparing an OpenAI-compatible gateway against an official baseline.
- The app should feel like a serious operational tool: dense, calm, easy to scan, and visually polished.

Files you should implement:
- `index.html`
- `styles.css`
- `app.js`

Hard requirements:
- Pure static site. Do not add a build step, package manager, external CDN, network calls, or external images.
- The page must load by opening `index.html` directly in a browser.
- Include visible UI for:
  - API configuration
  - model selection
  - quality scorecards
  - safety/privacy probes
  - token consumption
  - latency/stability
  - error breakdown
  - test case table
  - search and filter controls
  - export/download report action
- Include sample data for at least two providers: `official` and `gateway`.
- Add real client-side interaction:
  - search test cases
  - filter by status/category/provider
  - recompute and display summary metrics
  - update a details panel when a test case is selected

JavaScript API required by `verify.mjs`:
- `computeProviderSummary(runs)` returns an object keyed by provider.
- `filterCases(cases, filters)` supports `query`, `status`, `category`, and `provider`.
- `scoreGateway(summary)` returns a numeric score from 0 to 100.
- `formatPercent(value)` returns one-decimal percent text such as `87.5%`.
- `renderDashboard(data, state)` returns an HTML string containing the main dashboard markup.
- Expose these functions through both `module.exports` and `window.GatewayQualityApp` when those globals exist.

Design requirements:
- No hero/landing section. The first screen should be the actual dashboard.
- Do not put cards inside cards.
- Use stable responsive dimensions for scorecards, charts, filter controls, and tables.
- Do not use viewport-width font sizing or negative letter spacing.
- Use a restrained, multi-color palette. Avoid a one-note purple, beige, dark-slate, or orange/brown theme.
- Cards and controls should use border radius of 8px or less.
- Text must not overflow buttons, cards, or table cells on mobile or desktop.

Before finishing:
- Run `bash ./verify.sh`.
