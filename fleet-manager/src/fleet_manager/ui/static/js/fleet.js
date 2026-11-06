/**
 * Fleet Inventory, Health Status, Real-Time Filtering, and Node Selection.
 */

import {
  getOperatorToken,
  setSelectedNodeId,
  isFleetPending,
  setFleetPending,
  setCurrentFilter,
  setCurrentSearch,
  getLastFleetData,
  setLastFleetData,
  incrementSelectionEpoch,
  setHistoryOffset
} from "./state.js";
import { apiRequest, showAlert } from "./api.js";
import { openOnboardingModal } from "./node-onboarding.js";
import { fetchNodeOperationsHistory } from "./history.js";
import { renderInventory } from "./inventory-view.js";

let lastSuccessfulRefreshAt = null;

function refreshLabel(prefix) {
  const last = lastSuccessfulRefreshAt ? ` Last successful browser refresh: ${lastSuccessfulRefreshAt.toLocaleString()}.` : " No successful browser refresh yet.";
  return prefix + last;
}

/**
 * Fetch fleet status and update the inventory table and overview counters.
 */
export async function fetchFleetStatus() {
  const token = getOperatorToken();
  if (!token || isFleetPending()) return;

  setFleetPending(true);
  const lastUpdatedEl = document.getElementById("last-updated");
  if (lastUpdatedEl) {
    lastUpdatedEl.textContent = refreshLabel("Refreshing; displayed data pending verification.");
  }

  try {
    const res = await apiRequest("/api/nodes/status");
    if (!res.ok) throw new Error("Failed to load status");
    const data = await res.json();

    if (getOperatorToken() === token) {
      setLastFleetData(data);
      renderFleet(data);
      lastSuccessfulRefreshAt = new Date();
      if (lastUpdatedEl) lastUpdatedEl.textContent = refreshLabel("Browser refreshed successfully.");
      document.getElementById("inventory-card")?.removeAttribute("data-refresh-state");
    }
  } catch (err) {
    if (lastUpdatedEl) lastUpdatedEl.textContent = refreshLabel("Refresh failed; displayed inventory is stale/unverified.");
    document.getElementById("inventory-card")?.setAttribute("data-refresh-state", "unverified");
  } finally {
    setFleetPending(false);
  }
}

/** Render the API status response through the shared inventory view. */
export function renderFleet(fleetData) {
  renderInventory(fleetData, {
    selectNode,
    check: triggerConnectivityCheck,
    onboarding: openOnboardingModal
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
    row.className = row.dataset.nodeId === String(node.id) ? "selected-row" : "";
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
        b.setAttribute("aria-pressed", b === btn ? "true" : "false");
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
