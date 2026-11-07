/** Fleet summary and inventory presentation from one status response. */
import { getCurrentFilter, getCurrentSearch, getSelectedNodeId } from "./state.js";

const CONNECTIVITY = new Set(["REACHABLE", "UNREACHABLE", "CHECK_ERROR", "STALE", "NOT_CHECKED"]);
const SETUP = new Set(["READY", "HOST_KEY_REQUIRED", "AUTHENTICATION_REQUIRED", "CONFIGURATION_ERROR", "PENDING_SETUP"]);

function textElement(tag, className, value) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = value == null ? "" : String(value);
  return element;
}

function cell(label, className = "") {
  const element = document.createElement("td");
  element.dataset.label = label;
  element.className = className;
  return element;
}

function humanAge(seconds) {
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export function observationDetails(observation, ttlSeconds, status, now = Date.now()) {
  if (!observation) return { timestamp: "Never observed", age: "", expired: false };
  if (!observation.observed_at) return { timestamp: "Timestamp unavailable", age: "Age unavailable", expired: false };
  const date = new Date(observation.observed_at);
  const ageSeconds = Math.floor((now - date.getTime()) / 1000);
  if (!Number.isFinite(date.getTime()) || ageSeconds < 0) {
    return { timestamp: "Invalid timestamp", age: "Age unavailable", expired: false };
  }
  const validTtl = Number.isFinite(ttlSeconds) && ttlSeconds > 0;
  const expired = status === "STALE" || (validTtl && ageSeconds > ttlSeconds);
  return {
    timestamp: date.toLocaleString(),
    age: `${humanAge(ageSeconds)}${expired ? " · Expired" : validTtl ? "" : " · TTL unavailable"}`,
    expired
  };
}

function stateBadge(value, kind) {
  const state = kind === "connectivity" ? (CONNECTIVITY.has(value) ? value : "NOT_CHECKED")
    : (SETUP.has(value) ? value : "PENDING_SETUP");
  return textElement("span", `status-badge badge-${state.toLowerCase()}`, state);
}

function renderRow(item, ttlSeconds, actions) {
  const node = item.node || item;
  const status = CONNECTIVITY.has(item.display_status) ? item.display_status : "NOT_CHECKED";
  const setup = SETUP.has(item.setup_state) ? item.setup_state : "PENDING_SETUP";
  const observed = observationDetails(item.observation, ttlSeconds, status);
  const row = document.createElement("tr");
  row.dataset.nodeId = String(node.id);
  row.className = node.id === getSelectedNodeId() ? "selected-row" : "";
  row.tabIndex = 0;
  row.addEventListener("click", event => {
    if (event.target.closest?.("button")) return;
    actions.selectNode(node, status);
  });
  row.addEventListener("keydown", event => {
    if (event.target !== row || !["Enter", " "].includes(event.key)) return;
    event.preventDefault();
    actions.selectNode(node, status);
  });

  const name = cell("Node", "inventory-node");
  name.appendChild(textElement("span", "node-name-text", node.name));
  name.appendChild(textElement("span", "node-id-tag", `ID #${node.id}`));
  row.appendChild(name);

  const endpoint = cell("Endpoint", "endpoint-cell");
  const endpointValue = `${node.address}:${node.ssh_port}`;
  endpoint.textContent = endpointValue;
  endpoint.title = endpointValue;
  row.appendChild(endpoint);

  const connectivity = cell("Connectivity", "inventory-connectivity");
  connectivity.appendChild(stateBadge(status, "connectivity"));
  row.appendChild(connectivity);

  const setupCell = cell("Setup", "inventory-setup");
  setupCell.appendChild(stateBadge(setup, "setup"));
  row.appendChild(setupCell);

  const lastObserved = cell("Last observed", "inventory-observed");
  lastObserved.appendChild(textElement("span", "observed-time", observed.timestamp));
  if (observed.age) lastObserved.appendChild(textElement("span", observed.expired ? "observed-age is-expired" : "observed-age", observed.age));
  row.appendChild(lastObserved);

  const failure = cell("Failure reason", "inventory-reason");
  const reasons = [item.reason, item.observation?.error_category]
    .filter(Boolean).map(String).filter((value, index, all) => all.indexOf(value) === index);
  failure.textContent = reasons.join(" · ") || "—";
  failure.title = failure.textContent;
  row.appendChild(failure);

  const actionCell = cell("Actions", "inventory-actions");
  const check = textElement("button", "btn btn-secondary btn-sm", "Check SSH");
  check.type = "button";
  check.onclick = event => { event.stopPropagation(); actions.check(node.id, check); };
  const operations = textElement("button", "btn btn-primary btn-sm", "Operations");
  operations.type = "button";
  operations.onclick = event => { event.stopPropagation(); actions.selectNode(node, status, operations); };
  const setupAction = setup === "READY" ? "View setup" :
    setup === "CONFIGURATION_ERROR" || item.observation?.outcome === "HOST_KEY_MISMATCH" ? "Review setup issue" : "Continue setup";
  const setupButton = textElement("button", "btn btn-secondary btn-sm", setupAction);
  setupButton.type = "button";
  setupButton.onclick = event => { event.stopPropagation(); actions.onboarding(node); };
  actionCell.append(check, operations, setupButton);
  row.appendChild(actionCell);
  return row;
}

export function renderInventory(fleetData, actions) {
  const nodes = fleetData.nodes || [];
  const tbody = document.getElementById("nodes-table-body");
  if (!tbody) return;
  const counts = { REACHABLE: 0, UNREACHABLE: 0, CHECK_ERROR: 0, STALE: 0, NOT_CHECKED: 0 };
  for (const item of nodes) counts[CONNECTIVITY.has(item.display_status) ? item.display_status : "NOT_CHECKED"]++;
  for (const [id, value] of Object.entries({
    "stat-total": nodes.length, "stat-reachable": counts.REACHABLE,
    "stat-unreachable": counts.UNREACHABLE, "stat-errors": counts.CHECK_ERROR,
    "stat-stale": counts.STALE, "stat-not-checked": counts.NOT_CHECKED,
    "filter-count-all": nodes.length
  })) {
    const target = document.getElementById(id);
    if (target) target.textContent = String(value);
  }
  const ttl = fleetData.observation_ttl_seconds;
  const ttlLabel = document.getElementById("observation-ttl");
  if (ttlLabel) ttlLabel.textContent = Number.isFinite(ttl) && ttl > 0 ? `Observation TTL ${ttl}s` : "Observation TTL unavailable";

  const filter = getCurrentFilter();
  const search = getCurrentSearch();
  const visible = nodes.filter(item => {
    const node = item.node || item;
    if (filter !== "ALL" && item.display_status !== filter) return false;
    const terms = [node.name, node.address, node.ssh_port].map(value => String(value ?? "").toLowerCase());
    return !search || terms.some(value => value.includes(search));
  });
  const results = document.getElementById("inventory-results");
  if (results) results.textContent = nodes.length === 0 ? "No registered nodes" : `${visible.length} of ${nodes.length} nodes shown`;
  if (nodes.length === 0 || visible.length === 0) {
    const row = document.createElement("tr");
    const message = cell("", "empty-state");
    message.colSpan = 7;
    message.textContent = nodes.length === 0 ? "No nodes registered. Use Add Node to register a Linux host." : "No nodes match the selected filter or search query.";
    row.appendChild(message);
    tbody.replaceChildren(row);
    return;
  }
  tbody.replaceChildren(...visible.map(item => renderRow(item, ttl, actions)));
  const selected = visible.find(item => (item.node || item).id === getSelectedNodeId());
  if (selected) {
    const badge = document.getElementById("selected-node-badge");
    const status = CONNECTIVITY.has(selected.display_status) ? selected.display_status : "NOT_CHECKED";
    if (badge) { badge.textContent = status; badge.className = `status-badge badge-${status.toLowerCase()}`; }
    const warning = document.getElementById("ops-target-alert");
    if (warning) warning.style.display = status === "REACHABLE" ? "none" : "block";
  }
}
