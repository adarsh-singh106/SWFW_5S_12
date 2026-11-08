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

function svgElement(tag, attributes, text = "") {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  node.textContent = text;
  return node;
}

export function chartData(points, window, percent = false) {
  const end = Math.min(Number(window?.end) || Date.now() / 1000, Date.now() / 1000);
  const start = Number(window?.start) || end - 3600;
  const step = Number(window?.step) || 150;
  const samples = (Array.isArray(points) ? points : []).filter(point =>
    Array.isArray(point) && Number.isFinite(point[0]) && point[0] >= start && point[0] <= end
  ).sort((a, b) => a[0] - b[0]);
  const valid = value => Number.isFinite(value) && value >= 0 && (!percent || value <= 100);
  const maximum = percent ? 100 : Math.max(1, ...samples.filter(p => valid(p[1])).map(p => p[1])) * 1.1;
  const segments = [], accepted = [];
  let segment = [], previous = null;
  for (const [time, value] of samples) {
    if (previous !== null && time <= previous) continue;
    if (!valid(value) || previous !== null && time - previous > step * 1.5) {
      if (segment.length) segments.push(segment);
      segment = [];
    }
    previous = time;
    if (!valid(value)) continue;
    const point = { time, value, x: 48 + (time - start) / Math.max(1, end - start) * 536, y: 134 - value / maximum * 112 };
    segment.push(point); accepted.push(point);
  }
  if (segment.length) segments.push(segment);
  return { start, end, maximum, segments, samples: accepted, expected: Math.floor((end - start) / step) + 1 };
}

function trend(label, points, window, percent = false) {
  const box = element("div", "health-trend", "");
  box.appendChild(element("span", "health-metric-label", label));
  const data = chartData(points, window, percent);
  const format = value => percent ? `${value.toFixed(1)}%` : `${value.toFixed(1)} B/s`;
  box.appendChild(element("span", "health-coverage", `${data.samples.length}/${data.expected} reporting samples · last hour`));
  if (!data.samples.length) {
    box.appendChild(element("span", "health-unavailable", "History unavailable — no valid samples"));
    return box;
  }
  const svg = svgElement("svg", { viewBox: "0 0 600 170", preserveAspectRatio: "none", role: "group" });
  svg.setAttribute("aria-label", `${label} trend over the last hour`);
  const plot = element("div", "health-plot", "");
  for (const value of [0, data.maximum / 2, data.maximum]) {
    const y = 134 - value / data.maximum * 112;
    svg.appendChild(svgElement("line", { x1: 48, x2: 584, y1: y, y2: y, class: "health-gridline" }));
    const tick = element("span", "health-y-tick", value.toFixed(0));
    tick.style.top = `${y / 170 * 100}%`;
    plot.appendChild(tick);
  }
  const times = element("div", "health-time-axis", "");
  for (const time of [data.start, data.end]) times.appendChild(element("span", "", new Date(time * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })));
  for (const segment of data.segments) {
    svg.appendChild(svgElement("path", { d: segment.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(" "), fill: "none", stroke: "currentColor", "stroke-width": 2, "vector-effect": "non-scaling-stroke" }));
  }
  const inspection = element("output", "health-sample", "Inspect a point: hover, tap, or keyboard focus. Local time.");
  for (const point of data.samples) {
    const text = `${stamp(point.time)} · ${format(point.value)}`;
    const dot = svgElement("circle", { cx: point.x, cy: point.y, r: 4, tabindex: 0, role: "img", "aria-label": text });
    dot.appendChild(svgElement("title", {}, text));
    for (const event of ["pointerenter", "click", "focus"]) dot.addEventListener(event, () => { inspection.textContent = text; });
    svg.appendChild(dot);
  }
  plot.append(svg, times);
  box.appendChild(plot);
  box.appendChild(inspection);
  const insufficient = data.samples.length < 3;
  const hasGaps = data.segments.length > 1 || data.samples.length < data.expected;
  box.appendChild(element("span", "health-chart-state", insufficient ? "Collecting / insufficient history — fewer than 3 samples" : hasGaps ? "Partial coverage — gaps are not interpolated" : "Reporting across the requested window"));
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
  trends.append(
    trend("CPU utilization (%) · 5-minute rate", health.trends?.cpu_percent, health.window, true),
    trend("Memory used (%)", health.trends?.memory_percent, health.window, true),
    trend("Network receive (B/s) · 5-minute rate", health.trends?.receive_bytes_per_second, health.window),
    trend("Network transmit (B/s) · 5-minute rate", health.trends?.transmit_bytes_per_second, health.window)
  );
  const capacity = element("div", "health-capacity", "");
  capacity.appendChild(line("Root filesystem capacity", number(m.root_percent, "% used")));
  if (Number.isFinite(m.root_percent) && m.root_percent >= 0 && m.root_percent <= 100) {
    const meter = element("meter", "health-capacity-meter", "");
    meter.min = 0; meter.max = 100; meter.value = m.root_percent;
    meter.setAttribute("aria-label", "Root filesystem percent used");
    capacity.appendChild(meter);
  }
  container.replaceChildren(heading, subtitle, grid, capacity, trends);
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
