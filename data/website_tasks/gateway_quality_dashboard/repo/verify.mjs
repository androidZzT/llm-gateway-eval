import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const html = readFileSync("index.html", "utf8");
const css = readFileSync("styles.css", "utf8");
const js = readFileSync("app.js", "utf8");
const combined = `${html}\n${css}\n${js}`;

assert.match(html, /<main[^>]+id=["']app["']/i, "index.html should expose #app as the app root");
assert.match(html, /styles\.css/i, "index.html should load styles.css");
assert.match(html, /app\.js/i, "index.html should load app.js");
assert.doesNotMatch(combined, /https?:\/\//i, "site should not depend on external network resources");
assert.doesNotMatch(css, /font-size\s*:[^;]*vw/i, "do not use viewport-width font sizing");
assert.doesNotMatch(css, /letter-spacing\s*:\s*-/i, "do not use negative letter spacing");
assert.match(css, /@media/i, "styles.css should include responsive behavior");
assert.match(css, /grid-template-columns|flex/i, "styles.css should define real layout primitives");
assert.match(css, /border-radius\s*:\s*(?:[0-8]px|0)/i, "controls/cards should use modest rounded corners");

for (const phrase of [
  "LLM Gateway Quality Lab",
  "API",
  "model",
  "quality",
  "safety",
  "privacy",
  "token",
  "latency",
  "error",
  "search",
  "export",
]) {
  assert.ok(combined.toLowerCase().includes(phrase.toLowerCase()), `missing required UI phrase: ${phrase}`);
}

const sandbox = {
  module: { exports: {} },
  exports: {},
  window: {},
  console,
};
vm.runInNewContext(js, sandbox, { filename: "app.js" });
const api = sandbox.module.exports && Object.keys(sandbox.module.exports).length
  ? sandbox.module.exports
  : sandbox.window.GatewayQualityApp;

for (const fn of [
  "computeProviderSummary",
  "filterCases",
  "scoreGateway",
  "formatPercent",
  "renderDashboard",
]) {
  assert.equal(typeof api?.[fn], "function", `${fn} must be exported`);
}

const runs = [
  { id: "r1", provider: "official", category: "quality", status: "pass", latencyMs: 1200, inputTokens: 1000, outputTokens: 200, cost: 0.05 },
  { id: "r2", provider: "official", category: "safety", status: "pass", latencyMs: 900, inputTokens: 800, outputTokens: 150, cost: 0.04 },
  { id: "r3", provider: "gateway", category: "quality", status: "pass", latencyMs: 1600, inputTokens: 900, outputTokens: 180, cost: 0.03 },
  { id: "r4", provider: "gateway", category: "safety", status: "fail", latencyMs: 2400, inputTokens: 700, outputTokens: 120, cost: 0.02, errorType: "policy_leak" },
];
const cases = [
  { id: "case-quality", title: "Quality regression", provider: "gateway", category: "quality", status: "pass", tags: ["code", "json"] },
  { id: "case-privacy", title: "Privacy canary", provider: "gateway", category: "safety", status: "fail", tags: ["privacy", "canary"] },
  { id: "case-official", title: "Official baseline", provider: "official", category: "quality", status: "pass", tags: ["baseline"] },
];

const summary = api.computeProviderSummary(runs);
assert.equal(summary.official.total, 2, "official total should be counted");
assert.equal(summary.gateway.total, 2, "gateway total should be counted");
assert.equal(summary.official.passed, 2, "official passed should be counted");
assert.equal(summary.gateway.failed, 1, "gateway failed should be counted");
assert.ok(summary.gateway.totalTokens >= 1900, "gateway token total should include input and output tokens");
assert.ok(summary.gateway.avgLatencyMs >= 2000, "gateway average latency should be computed");

assert.deepEqual(
  api.filterCases(cases, { query: "privacy", status: "fail", category: "safety", provider: "gateway" }).map((item) => item.id),
  ["case-privacy"],
  "filterCases should combine query, status, category, and provider filters",
);
assert.deepEqual(
  api.filterCases(cases, { query: "json", status: "all", category: "all", provider: "all" }).map((item) => item.id),
  ["case-quality"],
  "filterCases should search tags as well as titles",
);

const score = api.scoreGateway(summary.gateway);
assert.ok(Number.isFinite(score), "scoreGateway should return a finite number");
assert.ok(score >= 0 && score <= 100, "scoreGateway should return 0..100");
assert.equal(api.formatPercent(0.875), "87.5%", "formatPercent should format one decimal percent");

const rendered = api.renderDashboard({ runs, cases }, { query: "", status: "all", category: "all", provider: "all" });
for (const phrase of ["official", "gateway", "Quality", "Safety", "Token", "Latency", "Privacy"]) {
  assert.ok(rendered.toLowerCase().includes(phrase.toLowerCase()), `renderDashboard output missing ${phrase}`);
}
