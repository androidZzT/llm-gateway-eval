import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const html = readFileSync("index.html", "utf8");
const css = readFileSync("styles.css", "utf8");
const js = readFileSync("app.js", "utf8");
const combined = `${html}\n${css}\n${js}`;

assert.match(html, /id=["']app["']/i);
assert.match(html, /styles\.css/i);
assert.match(html, /app\.js/i);
assert.doesNotMatch(combined, /https?:\/\//i);
assert.doesNotMatch(css, /font-size\s*:[^;]*vw/i);
assert.doesNotMatch(css, /letter-spacing\s*:\s*-/i);
assert.match(css, /@media/i, "responsive CSS required");
assert.match(css, /\.score|scorecard|score-card/i, "scorecard styling required");
assert.match(css, /grid|flex/i, "layout styling required");

const sandbox = { module: { exports: {} }, exports: {}, window: {}, console };
vm.runInNewContext(js, sandbox, { filename: "app.js" });
const api = Object.keys(sandbox.module.exports).length ? sandbox.module.exports : sandbox.window.GatewayCheck;

for (const fn of ["computeSummary", "filterCases", "renderDashboard", "formatPercent"]) {
  assert.equal(typeof api?.[fn], "function", `${fn} must be exported`);
}

const summary = api.computeSummary(api.sampleRuns);
assert.equal(summary.official.total, 2);
assert.equal(summary.gateway.total, 3);
assert.equal(summary.official.passRate, 1);
assert.equal(Math.round(summary.gateway.passRate * 100), 67);
assert.equal(summary.gateway.errorCount, 1);
assert.ok(summary.gateway.totalTokens > 1900);
assert.ok(summary.gateway.avgLatencyMs > 1000);

assert.deepEqual(
  api.filterCases(api.sampleCases, { query: "privacy", status: "fail", provider: "gateway" }).map((item) => item.id),
  ["secret-canary"],
);
assert.deepEqual(
  api.filterCases(api.sampleCases, { query: "json", status: "all", provider: "all" }).map((item) => item.id),
  ["json-output", "official-json"],
);
assert.equal(api.formatPercent(0.875), "87.5%");

const rendered = api.renderDashboard({ query: "", status: "all", provider: "all", selectedCaseId: "secret-canary" });
for (const phrase of [
  "GatewayCheck",
  "Gateway URL",
  "Model",
  "API Key Env",
  "Run check",
  "Quality",
  "Safety",
  "Privacy",
  "Token",
  "Latency",
  "Error",
  "Test Cases",
  "Export",
  "secret-canary",
]) {
  assert.ok(rendered.toLowerCase().includes(phrase.toLowerCase()), `rendered UI missing ${phrase}`);
}
