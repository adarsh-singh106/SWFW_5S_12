/** Native Fleet Health, backed only by the authenticated Prometheus proxy. */
import { apiRequest } from "./api.js";
import { isAuthenticated } from "./state.js";

let selectedId = null;
let generation = 0;
let cards = [];

function element(tag, className, text) {
  const node = document.createElement(tag);
  node.className = className;
  node.textContent = text;
  return node;
}

function number(value, suffix = "") {
  return typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(1)}${suffix}` : "Unavailable";
}

function bytes(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "Unavailable";
  return `${(value / (1024 ** 3)).toFixed(1)} GiB`;
}

function stamp(value) {
  const date = new Date(Number(value) * 1000);
  return value && Number.isFinite(date.getTime()) ? date.toLocaleString() : "Unavailable";
}

function line(label, value) {
  const row = element("div", "health-metric", "");
  row.append(element("span", "health-metric-label", label), element("strong", "health-metric-value", value));
  return row;
}

function trend(label, points) {
  const box = element("div", "health-trend", "");
  box.appendChild(element("span", "health-metric-label", label));
  if (!Array.isArray(points) || points.length < 2) {
    box.appendChild(element("span", "health-unavailable", "Trend unavailable"));
    return box;
  }
  const values = points.map(point => point[1]).filter(value => Number.isFinite(value));
  if (values.length < 2) return box;
  const min = Math.min(...values), max = Math.max(...values);
  const path = values.map((value, index) => `${index ? "L" : "M"}${(index * 100 / (values.length - 1)).toFixed(2)},${(35 - (value - min) * 30 / (max - min || 1)).toFixed(2)}`).join(" ");
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 100 40");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `${label} trend over the last hour`);
  const stroke = document.createElementNS("http://www.w3.org/2000/svg", "path");
  stroke.setAttribute("d", path);
  stroke.setAttribute("fill", "none");
  stroke.setAttribute("stroke", "currentColor");
  stroke.setAttribute("stroke-width", "2");
  svg.appendChild(stroke);
  box.appendChild(svg);
  return box;
}

function renderDetail() {
  const container = document.getElementById("health-detail");
  if (!container) return;
  const selected = cards.find(item => item.node.id === selectedId);
  if (!selected) {
    container.textContent = "Select a node to inspect detailed Linux telemetry.";
    return;
  }
  const { node, health } = selected;
  const m = health.metrics || {};
  const heading = element("h3", "health-detail-title", `${node.name} · ${health.status.toUpperCase()}`);
  const subtitle = element("p", "health-note", `Target: ${node.address} · Last scrape: ${stamp(health.observed_at)}`);
  const grid = element("div", "health-detail-grid", "");
  const used = typeof m.memory_total_bytes === "number" && typeof m.memory_used_bytes === "number" ? `${bytes(m.memory_used_bytes)} / ${bytes(m.memory_total_bytes)}` : "Unavailable";
  grid.append(
    line("CPU utilization", number(m.cpu_percent, "%")),
    line("Memory used / total", used),
    line("Root filesystem used", number(m.root_percent, "%")),
    line("Root available", bytes(m.root_available_bytes)),
    line("System uptime", typeof m.uptime_seconds === "number" ? `${(m.uptime_seconds / 3600).toFixed(1)} hours` : "Unavailable"),
    line("Load average (1 min)", number(m.load_one)),
    line("Network receive", number(m.receive_bytes_per_second, " B/s")),
    line("Network transmit", number(m.transmit_bytes_per_second, " B/s"))
  );
  const trends = element("div", "health-trends", "");
  trends.append(trend("CPU", health.trends?.cpu_percent), trend("Memory available", health.trends?.memory_available_bytes));
  container.replaceChildren(heading, subtitle, grid, trends);
}

export function selectHealthNode(id) {
  selectedId = id;
  renderDetail();
  document.querySelectorAll(".health-card").forEach(card => card.setAttribute("aria-pressed", card.dataset.nodeId === String(id) ? "true" : "false"));
}

export async function refreshHealth(items) {
  const current = ++generation;
  const nodes = items.map(item => item.node || item);
  const output = [];
  let next = 0;
  async function worker() {
    while (next < nodes.length) {
      const node = nodes[next++];
      let health;
      try {
        const response = await apiRequest(`/api/nodes/${node.id}/health`);
        health = response.ok ? await response.json() : { status: "unavailable", metrics: {}, trends: {} };
      } catch {
        health = { status: "unavailable", metrics: {}, trends: {} };
      }
      output.push({ node, health });
    }
  }
  await Promise.all(Array.from({ length: Math.min(4, nodes.length) }, worker));
  if (current !== generation || !isAuthenticated()) return;
  cards = output.sort((a, b) => a.node.id - b.node.id);
  const container = document.getElementById("health-cards");
  const overview = document.getElementById("health-overview");
  if (!container || !overview) return;
  if (!cards.length) {
    container.textContent = "Register a node to see its Linux telemetry.";
    overview.textContent = "No registered nodes";
    renderDetail();
    return;
  }
  const up = cards.filter(item => item.health.status === "up").length;
  overview.textContent = `${up} of ${cards.length} exporter targets reporting · ${cards.length - up} unavailable or down`;
  container.replaceChildren(...cards.map(({ node, health }) => {
    const card = element("button", "health-card", "");
    card.type = "button";
    card.dataset.nodeId = String(node.id);
    card.setAttribute("aria-pressed", node.id === selectedId ? "true" : "false");
    card.append(element("strong", "health-node-name", node.name), element("span", `health-target health-${health.status}`, health.status === "up" ? "Target up" : health.status === "down" ? "Target down" : health.status === "stale" ? "Stale scrape" : "Telemetry unavailable"));
    card.append(line("CPU", number(health.metrics?.cpu_percent, "%")), line("Memory", bytes(health.metrics?.memory_used_bytes)), line("Root used", number(health.metrics?.root_percent, "%")));
    card.appendChild(element("span", "health-last-scrape", `Last scrape: ${stamp(health.observed_at)}`));
    card.addEventListener("click", () => selectHealthNode(node.id));
    return card;
  }));
  if (selectedId === null || !cards.some(item => item.node.id === selectedId)) selectedId = cards[0].node.id;
  selectHealthNode(selectedId);
}
