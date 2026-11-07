/**
 * Remote Operations Audit History, Semantic Table Rendering & Honest Pagination.
 */

import {
  getSelectedNodeId,
  getSelectionEpoch,
  getHistorySequence,
  incrementHistorySequence,
  getHistoryOffset,
  setHistoryOffset,
  getInspectedOperationId,
  setInspectedOperationId
} from "./state.js";
import { apiRequest, showAlert } from "./api.js";
import { displayOperationResult, formatDuration, announce } from "./operations.js";

const PAGE_SIZE = 20;

/**
 * Initialize audit history toolbar and pagination listeners.
 */
export function initHistory() {
  const refreshBtn = document.getElementById("refresh-history-btn");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => {
      const selectedId = getSelectedNodeId();
      if (selectedId) {
        setHistoryOffset(0);
        fetchNodeOperationsHistory(selectedId);
      }
    });
  }

  const retryBtn = document.getElementById("history-retry-btn");
  if (retryBtn) {
    retryBtn.addEventListener("click", () => {
      const selectedId = getSelectedNodeId();
      if (selectedId) {
        fetchNodeOperationsHistory(selectedId);
      }
    });
  }

  const prevBtn = document.getElementById("history-prev-btn");
  if (prevBtn) {
    prevBtn.addEventListener("click", () => {
      const selectedId = getSelectedNodeId();
      if (!selectedId) return;
      const currentOffset = getHistoryOffset();
      setHistoryOffset(Math.max(0, currentOffset - PAGE_SIZE));
      fetchNodeOperationsHistory(selectedId);
    });
  }

  const nextBtn = document.getElementById("history-next-btn");
  if (nextBtn) {
    nextBtn.addEventListener("click", () => {
      const selectedId = getSelectedNodeId();
      if (!selectedId) return;
      const currentOffset = getHistoryOffset();
      setHistoryOffset(currentOffset + PAGE_SIZE);
      fetchNodeOperationsHistory(selectedId);
    });
  }
}

/**
 * Fetch and render operation history records for a selected node.
 * Guaranteed sequence and epoch ownership prevents stale overwrites.
 */
export async function fetchNodeOperationsHistory(nodeId) {
  const tbody = document.getElementById("history-table-body");
  const countBadge = document.getElementById("history-count-badge");
  const pageLabel = document.getElementById("history-page-label");
  const prevBtn = document.getElementById("history-prev-btn");
  const nextBtn = document.getElementById("history-next-btn");
  const errorBanner = document.getElementById("history-error-banner");
  const errorText = document.getElementById("history-error-text");

  if (!tbody) return;

  const epoch = getSelectionEpoch();
  const sequence = incrementHistorySequence();
  const offset = getHistoryOffset();

  if (errorBanner) errorBanner.style.display = "none";

  // Show loading indicator in table
  const loadingRow = document.createElement("tr");
  loadingRow.className = "history-item";
  const loadingCell = document.createElement("td");
  loadingCell.colSpan = 8;
  loadingCell.className = "empty-state";
  loadingCell.textContent = "Loading audit history...";
  loadingRow.appendChild(loadingCell);
  tbody.replaceChildren(loadingRow);

  try {
    const res = await apiRequest(`/api/nodes/${nodeId}/operations?include_output=false&limit=${PAGE_SIZE}&offset=${offset}`);
    if (!res.ok) throw new Error(`History fetch failed with HTTP ${res.status}`);
    const data = await res.json();

    // Verify epoch and sequence: discard stale responses
    if (nodeId !== getSelectedNodeId() || epoch !== getSelectionEpoch() || sequence !== getHistorySequence()) {
      return;
    }

    const ops = data.operations || [];

    // If an advanced page is empty, recover to previous page
    if (offset > 0 && ops.length === 0) {
      showAlert("No more records available.", "info");
      announce("No more historical records available; returned to previous page");
      setHistoryOffset(Math.max(0, offset - PAGE_SIZE));
      fetchNodeOperationsHistory(nodeId);
      return;
    }

    if (ops.length === 0 && offset === 0) {
      const emptyRow = document.createElement("tr");
      emptyRow.className = "history-item";
      const emptyCell = document.createElement("td");
      emptyCell.colSpan = 8;
      emptyCell.className = "empty-state";
      emptyCell.textContent = "No operations recorded yet for this node.";
      emptyRow.appendChild(emptyCell);
      tbody.replaceChildren(emptyRow);

      if (countBadge) countBadge.textContent = "0 records";
      if (pageLabel) pageLabel.textContent = "No records";
      if (prevBtn) prevBtn.disabled = true;
      if (nextBtn) nextBtn.disabled = true;
      return;
    }

    // Render table rows
    const rows = ops.map(op => {
      const tr = document.createElement("tr");
      tr.className = "history-item";
      tr.dataset.operationId = op.id;
      if (getInspectedOperationId() === op.id) {
        tr.classList.add("selected-history-row");
      }

      // Column 1: Requested Timestamp
      const tdTime = document.createElement("td");
      tdTime.textContent = op.requested_at ? new Date(op.requested_at).toLocaleTimeString() : "—";
      tr.appendChild(tdTime);

      // Column 2: Action Name
      const tdAction = document.createElement("td");
      tdAction.style.fontWeight = "600";
      tdAction.style.fontFamily = "var(--font-mono)";
      tdAction.textContent = op.action;
      tr.appendChild(tdAction);

      // Column 3: Arguments / Target Context
      const tdArgs = document.createElement("td");
      tdArgs.style.fontFamily = "var(--font-mono)";
      tdArgs.style.fontSize = "0.72rem";
      tdArgs.style.color = "var(--text-muted)";
      const args = op.arguments && Object.keys(op.arguments).length > 0
        ? JSON.stringify(op.arguments)
        : "—";
      tdArgs.textContent = args;
      tr.appendChild(tdArgs);

      // Column 4: Recorded Duration
      const tdDuration = document.createElement("td");
      tdDuration.textContent = formatDuration(op.started_at, op.completed_at);
      tr.appendChild(tdDuration);

      // Column 5: Exit Code
      const tdExit = document.createElement("td");
      tdExit.style.fontFamily = "var(--font-mono)";
      tdExit.textContent = (op.exit_code !== null && op.exit_code !== undefined) ? String(op.exit_code) : "—";
      tr.appendChild(tdExit);

      // Column 6: Failure Category
      const tdFail = document.createElement("td");
      tdFail.textContent = op.failure_category || "—";
      tr.appendChild(tdFail);

      // Column 7: Outcome Badge
      const tdOutcome = document.createElement("td");
      const badge = document.createElement("span");
      badge.className = `status-badge badge-${(op.outcome || "").toLowerCase()}`;
      badge.textContent = op.outcome || "UNKNOWN";
      tdOutcome.appendChild(badge);
      tr.appendChild(tdOutcome);

      // Column 8: Record Inspection Action
      const tdActionBtn = document.createElement("td");
      const inspectBtn = document.createElement("button");
      inspectBtn.type = "button";
      inspectBtn.className = "btn btn-secondary btn-sm inspect-btn";
      inspectBtn.textContent = "Inspect";
      inspectBtn.title = `Inspect historical execution output for job ${op.id}`;
      inspectBtn.onclick = async () => {
        try {
          const detail = await apiRequest(`/api/nodes/${nodeId}/operations/${op.id}`);
          if (!detail.ok) throw new Error("Operation detail unavailable");
          const record = await detail.json();
          if (epoch === getSelectionEpoch()) {
            setInspectedOperationId(op.id);
            document.querySelectorAll("#history-table-body tr").forEach(r => r.classList.remove("selected-history-row"));
            tr.classList.add("selected-history-row");
            displayOperationResult(record, true);
            announce(`Loaded historical operation record ${op.id}`);
          }
        } catch (err) {
          showAlert(err.message, "danger");
        }
      };
      tdActionBtn.appendChild(inspectBtn);
      tr.appendChild(tdActionBtn);

      return tr;
    });

    tbody.replaceChildren(...rows);

    // Update Honest Pagination Controls
    const startRecord = offset + 1;
    const endRecord = offset + ops.length;
    if (pageLabel) {
      pageLabel.textContent = `Showing records ${startRecord}–${endRecord}`;
    }
    if (countBadge) {
      countBadge.textContent = `${startRecord}–${endRecord}`;
    }
    if (prevBtn) {
      prevBtn.disabled = (offset === 0);
    }
    if (nextBtn) {
      nextBtn.disabled = (ops.length < PAGE_SIZE || offset >= 100000);
    }

    announce(`Audit history refreshed: showing records ${startRecord} through ${endRecord}`);
  } catch (err) {
    if (epoch === getSelectionEpoch() && sequence === getHistorySequence()) {
      if (errorBanner) {
        if (errorText) errorText.textContent = `Audit history unavailable: ${err.message}`;
        errorBanner.style.display = "block";
      }
      const errRow = document.createElement("tr");
      errRow.className = "history-item";
      const errCell = document.createElement("td");
      errCell.colSpan = 8;
      errCell.className = "empty-state";
      errCell.textContent = `Failed to load audit history: ${err.message}`;
      errRow.appendChild(errCell);
      tbody.replaceChildren(errRow);
    }
  }
}
