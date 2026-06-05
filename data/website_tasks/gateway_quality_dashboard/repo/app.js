function computeProviderSummary() {
  return {};
}

function filterCases(cases) {
  return cases;
}

function scoreGateway() {
  return 0;
}

function formatPercent(value) {
  return String(value);
}

function renderDashboard() {
  return "";
}

const api = {
  computeProviderSummary,
  filterCases,
  scoreGateway,
  formatPercent,
  renderDashboard,
};

if (typeof window !== "undefined") {
  window.GatewayQualityApp = api;
}

if (typeof module !== "undefined") {
  module.exports = api;
}
