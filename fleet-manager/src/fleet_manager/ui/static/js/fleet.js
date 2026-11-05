/**
 * Fleet Inventory, Health Status, Real-Time Filtering, and Node Selection.
 */

import {
  getOperatorToken,
  getSelectedNodeId,
  setSelectedNodeId,
  isFleetPending,
  setFleetPending,
  getCurrentFilter,
  setCurrentFilter,
  getCurrentSearch,
  setCurrentSearch,
  getLastFleetData,
  setLastFleetData,
  incrementSelectionEpoch,
  setHistoryOffset
} from "./state.js";
import { apiRequest, showAlert } from "./api.js";
import { openOnboardingModal } from "./node-onboarding.js";
import { fetchNodeOperationsHistory } from "./history.js";

/**
 * Fetch fleet status and update the inventory table and overview counters.
 */
export async function fetchFleetStatus() {
  const token = getOperatorToken();
  if (!token || isFleetPending()) return;

  setFleetPending(true);
  const lastUpdatedEl = document.getElementById("last-updated");
  if (lastUpdatedEl) {
    lastUpdatedEl.textContent = "Refreshing; previous data unverified...";
  }

  try {
    const res = await apiRequest("/api/nodes/status");
    if (!res.ok) throw new Error("Failed to load status");
    const data = await res.json();

    if (getOperatorToken() === token) {
      setLastFleetData(data);
      renderFleet(data);
    }
  } catch (err) {
    if (err.message !== "Unauthorized") {
      if (lastUpdatedEl) {
        lastUpdatedEl.textContent = "Refresh failed - displayed data stale: " + err.message;
      }
      document.querySelectorAll("#nodes-table-body tr[data-node-id]").forEach(row => {
        if (row.children && row.children[3]) {
          row.children[3].textContent = "Unverified / stale";
        }
      });
      const badge = document.getElementById("selected-node-badge");
      if (badge) badge.textContent = "UNVERIFIED";
    }
  } finally {
    setFleetPending(false);
  }
}

/**
 * Render fleet summary counters, availability ratio, and node table rows.
 */
export function renderFleet(fleetData) {
  const nodes = fleetData.nodes || [];
  const tbody = document.getElementById("nodes-table-body");
  if (!tbody) return;

  // Count fleet states
  let reachable = 0, unreachable = 0, errors = 0, stale = 0, notChecked = 0;
  nodes.forEach(item => {
    const s = item.display_status || (item.node ? item.node.observation_state : "NOT_CHECKED");
    if (s === "REACHABLE") reachable++;
    else if (s === "UNREACHABLE") unreachable++;
    else if (s === "CHECK_ERROR") errors++;
    else if (s === "STALE") stale++;
    else notChecked++;
  });

  const setElText = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  };

  setElText("stat-total", nodes.length);
  setElText("stat-reachable", reachable);
  setElText("stat-unreachable", unreachable);
  setElText("stat-errors", errors);
  setElText("stat-stale", stale);
  setElText("stat-not-checked", notChecked);

  const countAllEl = document.getElementById("filter-count-all");
  if (countAllEl) countAllEl.textContent = nodes.length;

  // Honest availability calculation
  const observedTotal = reachable + unreachable + errors + stale;
  const availPercentEl = document.getElementById("availability-percent");
  const availTextEl = document.getElementById("availability-summary-text");
  const barReachable = document.getElementById("avail-bar-reachable");
  const barStale = document.getElementById("avail-bar-stale");
  const barUnreachable = document.getElementById("avail-bar-unreachable");

  if (observedTotal === 0) {
    if (availPercentEl) availPercentEl.textContent = "—";
    if (availTextEl) {
      availTextEl.innerHTML = 'Observed Nodes Availability: <strong style="color: var(--text-primary);">—</strong> <span style="font-size: 0.7rem; color: var(--text-muted); margin-left: 0.4rem;">(Awaiting first probes)</span>';
    }
    if (barReachable) barReachable.style.width = "0%";
    if (barStale) barStale.style.width = "0%";
    if (barUnreachable) barUnreachable.style.width = "0%";
  } else {
    const pct = ((reachable / observedTotal) * 100).toFixed(1);
    if (availPercentEl) availPercentEl.textContent = pct + "%";
    if (availTextEl) {
      const color = reachable === observedTotal ? 'var(--success-text)' : 'var(--text-primary)';
      availTextEl.innerHTML = `Observed Nodes Availability: <strong style="color: ${color};">${pct}%</strong> <span style="font-size: 0.7rem; color: var(--text-muted); margin-left: 0.4rem;">(${reachable} of ${observedTotal} observed nodes)</span>`;
    }
    if (barReachable) barReachable.style.width = `${(reachable / observedTotal) * 100}%`;
    if (barStale) barStale.style.width = `${(stale / observedTotal) * 100}%`;
    if (barUnreachable) barUnreachable.style.width = `${((unreachable + errors) / observedTotal) * 100}%`;
  }

  const lastUpdatedEl = document.getElementById("last-updated");
  if (lastUpdatedEl) {
    lastUpdatedEl.textContent = "Updated: " + new Date().toLocaleTimeString();
  }

  if (nodes.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty-state"><div class="empty-state-icon">📦</div><div>No nodes registered. Use the "+ Add Node" form above to onboard a Linux host.</div></td></tr>';
    return;
  }

  const currentFilter = getCurrentFilter();
  const currentSearch = getCurrentSearch();

  const filteredNodes = nodes.filter(item => {
    const node = item.node || item;
    const displayStatus = item.display_status || node.observation_state || "NOT_CHECKED";
    if (currentFilter !== "ALL" && displayStatus !== currentFilter) return false;
    if (currentSearch) {
      const matchName = (node.name || "").toLowerCase().includes(currentSearch);
      const matchAddr = (node.address || "").toLowerCase().includes(currentSearch);
      const matchPort = String(node.ssh_port || "").includes(currentSearch);
      if (!matchName && !matchAddr && !matchPort) return false;
    }
    return true;
  });

  if (filteredNodes.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No nodes match the selected filter or search query.</td></tr>';
    return;
  }

  // Reconcile against the filtered set, not all inventory IDs.
  const visibleIds = new Set(filteredNodes.map(item => String((item.node || item).id)));
  Array.from(tbody.children || []).forEach(row => {
    if (!visibleIds.has(row.dataset.nodeId)) row.remove();
  });
  const selectedId = getSelectedNodeId();

  filteredNodes.forEach(item => {
    const node = item.node || item;
    const displayStatus = item.display_status || node.observation_state || "NOT_CHECKED";
    const setupState = item.setup_state || "PENDING_SETUP";
    const reason = item.reason || (item.observation ? item.observation.error_category : null);
    const lastObservedAt = item.observation ? item.observation.observed_at : null;

    const tr = document.createElement("tr");
    tr.dataset.nodeId = String(node.id);
    if (node.id === selectedId) {
      tr.className = "selected-row";
    }

    // Status Badge Cell (Both connectivity status and setup indicator)
    const tdStatus = document.createElement("td");
    const badgeWrap = document.createElement("div");
    badgeWrap.style.display = "flex";
    badgeWrap.style.flexDirection = "column";
    badgeWrap.style.gap = "0.2rem";

    const badge = document.createElement("span");
    badge.className = `status-badge badge-${displayStatus.toLowerCase()}`;
    badge.textContent = displayStatus;
    badgeWrap.appendChild(badge);

    // Setup state mini badge if not READY
    if (setupState && setupState !== "READY") {
      const setupBadge = document.createElement("span");
      setupBadge.style.fontSize = "0.62rem";
      setupBadge.style.color = "var(--text-muted)";
      setupBadge.textContent = setupState.replace("_", " ");
      badgeWrap.appendChild(setupBadge);
    }
    tdStatus.appendChild(badgeWrap);
    tr.appendChild(tdStatus);

    // Name Cell (safe textContent to prevent XSS)
    const tdName = document.createElement("td");
    const nameWrapper = document.createElement("div");
    nameWrapper.className = "node-title-cell";
    const nameSpan = document.createElement("span");
    nameSpan.className = "node-name-text";
    nameSpan.textContent = node.name;
    const idSpan = document.createElement("span");
    idSpan.className = "node-id-tag";
    idSpan.textContent = `ID #${node.id}`;
    nameWrapper.appendChild(nameSpan);
    nameWrapper.appendChild(idSpan);
    tdName.appendChild(nameWrapper);
    tr.appendChild(tdName);

    // Endpoint Cell
    const tdEndpoint = document.createElement("td");
    tdEndpoint.className = "endpoint-cell";
    tdEndpoint.textContent = `${node.address}:${node.ssh_port}`;
    tr.appendChild(tdEndpoint);

    // Freshness Cell
    const tdFreshness = document.createElement("td");
    if (displayStatus === "NOT_CHECKED" || lastObservedAt === null) {
      tdFreshness.innerHTML = '<span style="color: var(--text-muted);">Never</span>';
    } else if (displayStatus === "STALE") {
      tdFreshness.innerHTML = '<span style="color: var(--stale-text); font-weight: 600;">Stale</span>';
    } else {
      tdFreshness.innerHTML = '<span style="color: var(--success-text); font-weight: 600;">Fresh</span>';
    }
    tr.appendChild(tdFreshness);

    // Last Observed Timestamp Cell
    const tdObserved = document.createElement("td");
    tdObserved.style.fontSize = "0.75rem";
    tdObserved.style.color = "var(--text-muted)";
    tdObserved.style.whiteSpace = "nowrap";
    if (lastObservedAt) {
      const d = new Date(lastObservedAt);
      tdObserved.textContent = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      if (typeof tdObserved.setAttribute === "function") {
        tdObserved.setAttribute("title", d.toLocaleString());
      }
    } else {
      tdObserved.textContent = "Never";
    }
    tr.appendChild(tdObserved);

    // Diagnostic details Cell
    const tdDiag = document.createElement("td");
    if (reason) {
      const errSpan = document.createElement("span");
      errSpan.style.color = "var(--danger-text)";
      errSpan.style.fontFamily = "var(--font-mono)";
      errSpan.style.fontSize = "0.75rem";
      errSpan.textContent = reason;
      tdDiag.appendChild(errSpan);
    } else if (displayStatus === "REACHABLE") {
      tdDiag.innerHTML = '<span style="color: var(--success-text); font-size: 0.75rem;">Connected (SSHv2)</span>';
    } else {
      tdDiag.innerHTML = '<span style="color: var(--text-muted); font-size: 0.75rem;">—</span>';
    }
    tr.appendChild(tdDiag);

    // Actions Cell
    const tdActions = document.createElement("td");
    tdActions.style.whiteSpace = "nowrap";
    tdActions.style.display = "flex";
    tdActions.style.gap = "0.3rem";
    tdActions.style.alignItems = "center";

    const checkBtn = document.createElement("button");
    checkBtn.className = "btn btn-secondary btn-sm";
    checkBtn.style.padding = "0.22rem 0.45rem";
    checkBtn.style.fontSize = "0.72rem";
    checkBtn.textContent = "Check SSH";
    checkBtn.onclick = (e) => {
      e.stopPropagation();
      triggerConnectivityCheck(node.id, checkBtn);
    };
    tdActions.appendChild(checkBtn);

    const opsBtn = document.createElement("button");
    opsBtn.className = "btn btn-primary btn-sm";
    opsBtn.style.padding = "0.22rem 0.45rem";
    opsBtn.style.fontSize = "0.72rem";
    opsBtn.textContent = "Operations";
    opsBtn.onclick = () => { selectNode(node, displayStatus); };
    tdActions.appendChild(opsBtn);
    const setupBtn = document.createElement("button");
    setupBtn.className = "btn btn-secondary btn-sm";
    setupBtn.textContent = setupState === "READY" ? "Review setup" : "Resume onboarding";
    setupBtn.onclick = () => openOnboardingModal(node);
    tdActions.appendChild(setupBtn);

    tr.appendChild(tdActions);

    const existing = tbody.children ? Array.from(tbody.children).find(row => row.dataset.nodeId === String(node.id)) : null;
    if (existing) {
      existing.className = tr.className;
      for (let i = 0; i < 6; i++) {
        if (existing.children[i] && tr.children[i]) {
          existing.children[i].innerHTML = tr.children[i].innerHTML;
        }
      }
      if (existing.children[6] && existing.children[6].lastElementChild) {
        existing.children[6].children[1].onclick = () => selectNode(node, displayStatus);
        existing.children[6].lastElementChild.onclick = () => openOnboardingModal(node);
      }
    } else {
      tbody.appendChild(tr);
    }

    if (node.id === selectedId) {
      const selectedBadge = document.getElementById("selected-node-badge");
      if (selectedBadge) {
        selectedBadge.textContent = displayStatus;
        selectedBadge.className = badge.className;
      }
      const targetAlert = document.getElementById("ops-target-alert");
      if (targetAlert) {
        targetAlert.style.display = (displayStatus !== "REACHABLE") ? "block" : "none";
      }
    }
  });
}

/**
 * Trigger a manual SSH connectivity check.
 */
export async function triggerConnectivityCheck(nodeId, btn) {
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>';
  }

  try {
    const res = await apiRequest(`/api/nodes/${nodeId}/connectivity-check`, {
      method: "POST"
    });
    const data = await res.json();
    if (res.ok) {
      showAlert(`Check completed for node ${nodeId}: ${data.outcome}`, data.outcome === "CONNECTED" ? "success" : "warning");
      fetchFleetStatus();
    } else {
      showAlert(`Check failed: ${data.error ? data.error.message : 'Unknown error'}`, "danger");
    }
  } catch (err) {
    showAlert("Error triggering check: " + err.message, "danger");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Check SSH";
    }
  }
}

/**
 * Select a node for remote operations and audit inspection.
 */
export function selectNode(node, displayStatus) {
  incrementSelectionEpoch();
  setHistoryOffset(0);
  setSelectedNodeId(node.id);

  const status = displayStatus || node.observation_state || "NOT_CHECKED";

  const emptyState = document.getElementById("ops-empty-state");
  const activePanel = document.getElementById("ops-active-panel");
  if (emptyState) emptyState.style.display = "none";
  if (activePanel) activePanel.style.display = "block";

  const titleEl = document.getElementById("ops-node-title");
  if (titleEl) titleEl.textContent = `Operations: ${node.name}`;

  const subtitleEl = document.getElementById("ops-node-subtitle");
  if (subtitleEl) subtitleEl.textContent = `Target SSH Endpoint: ${node.address}:${node.ssh_port}`;

  const badge = document.getElementById("selected-node-badge");
  if (badge) {
    badge.textContent = status;
    badge.className = `status-badge badge-${status.toLowerCase()}`;
    badge.style.display = "inline-flex";
  }

  const targetAlert = document.getElementById("ops-target-alert");
  if (targetAlert) {
    targetAlert.style.display = (status !== "REACHABLE") ? "block" : "none";
  }

  const opResultBox = document.getElementById("op-result-box");
  if (opResultBox) opResultBox.style.display = "none";

  const historyList = document.getElementById("history-list");
  if (historyList) historyList.textContent = "Loading history...";

  fetchNodeOperationsHistory(node.id);

  document.querySelectorAll("#nodes-table-body tr").forEach(row => {
    if (row.classList && typeof row.classList.toggle === "function") {
      row.classList.toggle("selected-row", row.dataset.nodeId === String(node.id));
    } else {
      row.className = row.dataset.nodeId === String(node.id) ? "selected-row" : "";
    }
  });
}

/**
 * Initialize fleet toolbar listeners (search, filters, refresh).
 */
export function initFleet() {
  const searchInput = document.getElementById("search-input");
  if (searchInput) {
    searchInput.addEventListener("input", (e) => {
      setCurrentSearch((e.target.value || "").trim().toLowerCase());
      const data = getLastFleetData();
      if (data) renderFleet(data);
    });
  }

  const filterBtns = Array.from(document.querySelectorAll(".filter-btn"));
  filterBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      filterBtns.forEach(b => {
        if (b.classList && typeof b.classList.toggle === "function") {
          b.classList.toggle("active", b === btn);
        } else {
          b.className = b === btn ? "filter-btn active" : "filter-btn";
        }
      });
      setCurrentFilter(btn.dataset.filter || "ALL");
      const data = getLastFleetData();
      if (data) renderFleet(data);
    });
  });

  const refreshBtn = document.getElementById("refresh-btn");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => {
      fetchFleetStatus();
    });
  }
}
