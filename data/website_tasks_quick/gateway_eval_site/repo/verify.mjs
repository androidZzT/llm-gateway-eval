import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const html = readFileSync("index.html", "utf8");
const css = readFileSync("styles.css", "utf8");
const js = readFileSync("app.js", "utf8");
const combined = `${html}\n${css}\n${js}`;

assert.match(html, /id=["']app["']/i, "index.html must include #app");
assert.match(html, /styles\.css/i, "index.html must load styles.css");
assert.match(html, /app\.js/i, "index.html must load app.js");
assert.doesNotMatch(combined, /https?:\/\//i, "no external network resources");
assert.doesNotMatch(css, /font-size\s*:[^;]*vw/i, "no viewport-width font sizing");
assert.doesNotMatch(css, /letter-spacing\s*:\s*-/i, "no negative letter spacing");
assert.match(css, /@media/i, "responsive media query required");
assert.match(css, /\.score|scorecard|score-card/i, "scorecard styles required");
assert.match(css, /grid|flex/i, "layout styles required");

const sandbox = { module: { exports: {} }, exports: {}, window: {}, console };
vm.runInNewContext(js, sandbox, { filename: "app.js" });
const api = Object.keys(sandbox.module.exports).length ? sandbox.module.exports : sandbox.window.GatewayCheck;

for (const fn of ["computeSummary", "filterCases", "renderDashboard", "formatPercent"]) {
  assert.equal(typeof api?.[fn], "function", `${fn} must be exported`);
}

const runs = api.sampleRuns;
const cases = api.sampleCases;
const summary = api.computeSummary(runs);
assert.equal(summary.official.total, 2, "official total");
assert.equal(summary.gateway.total, 3, "gateway total");
assert.equal(summary.official.passRate, 1, "official pass rate");
assert.equal(Math.round(summary.gateway.passRate * 100), 67, "gateway pass rate");
assert.equal(summary.gateway.errorCount, 1, "gateway error count");
assert.ok(summary.gateway.totalTokens > 1900, "gateway token total");
assert.ok(summary.gateway.avgLatencyMs > 1000, "gateway average latency");

assert.deepEqual(
  api.filterCases(cases, { query: "privacy", status: "fail", provider: "gateway" }).map((item) => item.id),
  ["secret-canary"],
  "combined filters should work",
);
assert.deepEqual(
  api.filterCases(cases, { query: "json", status: "all", provider: "all" }).map((item) => item.id),
  ["json-output", "official-json"],
  "search should include title/tags/id",
);
assert.equal(api.formatPercent(0.875), "87.5%", "percent formatting");

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
