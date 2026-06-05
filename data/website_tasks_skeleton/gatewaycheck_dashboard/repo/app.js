const sampleRuns = [
  { id: "r1", provider: "official", caseId: "json-output", category: "quality", status: "pass", latencyMs: 940, inputTokens: 820, outputTokens: 180, cost: 0.024 },
  { id: "r2", provider: "official", caseId: "secret-canary", category: "safety", status: "pass", latencyMs: 1120, inputTokens: 760, outputTokens: 120, cost: 0.021 },
  { id: "r3", provider: "gateway", caseId: "json-output", category: "quality", status: "pass", latencyMs: 1280, inputTokens: 790, outputTokens: 170, cost: 0.018 },
  { id: "r4", provider: "gateway", caseId: "secret-canary", category: "safety", status: "fail", latencyMs: 2200, inputTokens: 710, outputTokens: 110, cost: 0.016, errorType: "privacy_echo" },
  { id: "r5", provider: "gateway", caseId: "ping", category: "stability", status: "pass", latencyMs: 860, inputTokens: 120, outputTokens: 20, cost: 0.004 },
];

const sampleCases = [
  { id: "json-output", title: "JSON schema output", provider: "gateway", category: "quality", status: "pass", tags: ["json", "compatibility"] },
  { id: "secret-canary", title: "Privacy canary", provider: "gateway", category: "safety", status: "fail", tags: ["privacy", "security"] },
  { id: "ping", title: "Latency ping", provider: "gateway", category: "stability", status: "pass", tags: ["latency", "network"] },
  { id: "official-json", title: "Official JSON baseline", provider: "official", category: "quality", status: "pass", tags: ["baseline", "json"] },
];

function computeSummary(runs = sampleRuns) {
  // TODO: return provider summaries keyed by official/gateway.
  return {};
}

function filterCases(cases = sampleCases, filters = {}) {
  // TODO: filter by query, status, and provider.
  return cases;
}

function formatPercent(value) {
  // TODO: return one-decimal percent text.
  return String(value);
}

function renderDashboard(state = {}) {
  // TODO: render the complete dashboard markup.
  return "";
}

function mount() {
  const root = typeof document !== "undefined" ? document.getElementById("app") : null;
  if (!root) return;
  let state = { query: "", status: "all", provider: "all", selectedCaseId: "secret-canary" };
  const render = () => {
    root.innerHTML = renderDashboard(state);
    root.querySelector("#case-search")?.addEventListener("input", (event) => {
      state = { ...state, query: event.target.value };
      render();
    });
    root.querySelector("#status-filter")?.addEventListener("change", (event) => {
      state = { ...state, status: event.target.value };
      render();
    });
    root.querySelector("#provider-filter")?.addEventListener("change", (event) => {
      state = { ...state, provider: event.target.value };
      render();
    });
    root.querySelectorAll("[data-case-id]").forEach((row) => {
      row.addEventListener("click", () => {
        state = { ...state, selectedCaseId: row.getAttribute("data-case-id") };
        render();
      });
    });
  };
  render();
}

const api = { computeSummary, filterCases, formatPercent, renderDashboard, sampleRuns, sampleCases };

if (typeof window !== "undefined") {
  window.GatewayCheck = api;
  mount();
}

if (typeof module !== "undefined") {
  module.exports = api;
}
