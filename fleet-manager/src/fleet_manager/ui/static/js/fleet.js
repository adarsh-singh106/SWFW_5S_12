/**
 * Fleet Inventory, Health Status, Real-Time Filtering, and Node Selection.
 */

import {
  getOperatorToken,
  isAuthenticated,
  getMustChangePassword,
  setSelectedNodeId,
  isFleetPending,
  setFleetPending,
  setCurrentFilter,
  setCurrentSearch,
  getLastFleetData,
  setLastFleetData,
  incrementSelectionEpoch,
  setHistoryOffset,
  setInspectedOperationId,
  setInventoryReturnFocus
} from "./state.js";
import { apiRequest, showAlert } from "./api.js";
import { openOnboardingModal } from "./node-onboarding.js";
import { fetchNodeOperationsHistory } from "./history.js";
import { renderInventory } from "./inventory-view.js";
import { refreshHealth, selectHealthNode } from "./health.js";
import {
  updateExecButtonState,
  getLatestNodeResult,
  displayOperationResult,
  showStandbyInspector
} from "./operations.js";

let lastSuccessfulRefreshAt = null;

function refreshLabel(prefix) {
  const last = lastSuccessfulRefreshAt ? ` Last successful browser refresh: ${lastSuccessfulRefreshAt.toLocaleString()}.` : " No successful browser refresh yet.";
  return prefix + last;
}

/**
 * Fetch fleet status and update the inventory table and overview counters.
 */
export async function fetchFleetStatus() {
  if (!isAuthenticated() || getMustChangePassword() || isFleetPending()) return;

  setFleetPending(true);
  const lastUpdatedEl = document.getElementById("last-updated");
  if (lastUpdatedEl) {
    lastUpdatedEl.textContent = refreshLabel("Refreshing; displayed data pending verification.");
  }

  try {
    const res = await apiRequest("/api/nodes/status");
    if (!res.ok) throw new Error("Failed to load status");
    const data = await res.json();

    if (isAuthenticated()) {
      setLastFleetData(data);
      renderFleet(data);
      void refreshHealth(data.nodes || []);
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
  const guidance = document.getElementById("ssh-config-guidance");
  if (guidance) {
    const issues = Array.isArray(fleetData.configuration_issues) ? fleetData.configuration_issues : [];
    const configured = issues.length > 0 || (fleetData.nodes || []).some(item => item.setup_state === "CONFIGURATION_ERROR");
    guidance.hidden = !configured;
    guidance.textContent = configured ? `SSH configuration needs attention. ${issues.length ? `Missing or invalid: ${issues.join(", ")}. ` : ""}Set a non-root SSH user, an existing known_hosts file, and a protected private key file. Review node setup before retrying.` : "";
  }
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
      const explanations = {
        DNS_ERROR: "Hostname could not be resolved by DNS. Verify the registered name and resolver.",
        CONNECTION_REFUSED: "The address resolved, but SSH refused the connection. Check the SSH service and port.",
        CONNECTION_TIMEOUT: "The SSH connection timed out. Check routing and firewall access."
      };
      showAlert(`Check completed for node ${nodeId}: ${data.outcome}. ${explanations[data.outcome] || ""}`, data.outcome === "CONNECTED" ? "success" : "warning");
      fetchFleetStatus();
    } else {
      if (res.status === 503 && data.error?.code === "connectivity_unavailable") {
        const guidance = document.getElementById("ssh-config-guidance");
        if (guidance) {
          guidance.hidden = false;
          guidance.textContent = "SSH settings are missing or invalid. Configure FLEET_MANAGER_SSH_USERNAME, FLEET_MANAGER_SSH_KNOWN_HOSTS, and FLEET_MANAGER_SSH_PRIVATE_KEY on the server, then retry this node's check.";
        }
      } else {
        showAlert(`Check failed: ${data.error ? data.error.message : 'Unknown error'}`, "danger");
      }
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
export function selectNode(node, displayStatus, triggerEl = null) {
  incrementSelectionEpoch();
  setHistoryOffset(0);
  setInspectedOperationId(null);
  setSelectedNodeId(node.id);
  selectHealthNode(node.id);
  if (triggerEl) {
    setInventoryReturnFocus(triggerEl);
  }

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

  const statusPill = document.getElementById("ops-target-status-pill");
  if (statusPill) {
    statusPill.textContent = status;
    statusPill.className = `status-badge badge-${status.toLowerCase()}`;
  }

  const targetAlert = document.getElementById("ops-target-alert");
  if (targetAlert) {
    targetAlert.style.display = (status !== "REACHABLE") ? "block" : "none";
  }

  // Node-specific dispatch button state (do not inherit lock from another node)
  updateExecButtonState(node.id);

  // Inspector state: show latest execution result for this node if present, else standby
  const latestResult = getLatestNodeResult(node.id);
  if (latestResult) {
    displayOperationResult(latestResult, false);
  } else {
    showStandbyInspector();
  }

  fetchNodeOperationsHistory(node.id);

  document.querySelectorAll("#nodes-table-body tr").forEach(row => {
    row.className = row.dataset.nodeId === String(node.id) ? "selected-row" : "";
  });

  // Scroll workbench into view and move keyboard focus appropriately
  const workbench = document.getElementById("operations-workbench");
  if (workbench) {
    const reducedMotion = typeof window !== "undefined" && window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    workbench.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
  }

  const returnBtn = document.getElementById("return-to-inventory-btn");
  if (returnBtn && typeof returnBtn.focus === "function") {
    returnBtn.focus();
  }
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
