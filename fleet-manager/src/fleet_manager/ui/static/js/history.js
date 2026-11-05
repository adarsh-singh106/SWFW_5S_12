/**
 * Remote Operations Audit History & Pagination.
 */

import {
  getSelectedNodeId,
  getSelectionEpoch,
  getHistorySequence,
  incrementHistorySequence,
  getHistoryOffset,
  setHistoryOffset
} from "./state.js";
import { apiRequest, showAlert } from "./api.js";
import { displayOperationResult } from "./operations.js";

export function initHistory() {
  const refreshHistoryBtn = document.getElementById("refresh-history-btn");
  if (refreshHistoryBtn) {
    refreshHistoryBtn.addEventListener("click", () => {
      const selectedId = getSelectedNodeId();
      if (selectedId) {
        setHistoryOffset(0);
        fetchNodeOperationsHistory(selectedId);
      }
    });
  }
}

/**
 * Fetch and render operation history records for a selected node.
 * Guaranteed sequence and epoch ownership prevents stale overwrites.
 */
export async function fetchNodeOperationsHistory(nodeId) {
  const listContainer = document.getElementById("history-list");
  if (!listContainer) return;

  const epoch = getSelectionEpoch();
  const sequence = incrementHistorySequence();
  const offset = getHistoryOffset();

  try {
    const res = await apiRequest(`/api/nodes/${nodeId}/operations?include_output=false&limit=20&offset=${offset}`);
    if (!res.ok) throw new Error("History refresh failed");
    const data = await res.json();

    // Verify epoch and sequence: discard stale responses
    if (nodeId !== getSelectedNodeId() || epoch !== getSelectionEpoch() || sequence !== getHistorySequence()) {
      return;
    }

    const ops = data.operations || [];

    if (ops.length === 0 && offset === 0) {
      listContainer.innerHTML = '<div class="empty-state" style="padding: 1rem;">No operations recorded yet for this node.</div>';
      return;
    }

    listContainer.innerHTML = "";
    ops.forEach(op => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "history-item";

      const left = document.createElement("div");
      const actionSpan = document.createElement("div");
      actionSpan.style.fontWeight = "600";
      actionSpan.style.color = "var(--text-primary)";
      actionSpan.textContent = op.action;
      const timeSpan = document.createElement("div");
      timeSpan.style.color = "var(--text-muted)";
      timeSpan.style.fontSize = "0.7rem";
      timeSpan.textContent = new Date(op.requested_at).toLocaleTimeString();
      left.appendChild(actionSpan);
      left.appendChild(timeSpan);

      const right = document.createElement("div");
      right.style.display = "flex";
      right.style.alignItems = "center";
      right.style.gap = "0.4rem";

      if (op.exit_code !== null && op.exit_code !== undefined) {
        const exitPill = document.createElement("span");
        exitPill.style.fontSize = "0.68rem";
        exitPill.style.color = "var(--text-muted)";
        exitPill.style.fontFamily = "var(--font-mono)";
        exitPill.textContent = `exit ${op.exit_code}`;
        right.appendChild(exitPill);
      }

      const badge = document.createElement("span");
      badge.className = `status-badge badge-${(op.outcome || "").toLowerCase()}`;
      badge.textContent = op.outcome;
      right.appendChild(badge);

      item.appendChild(left);
      item.appendChild(right);

      item.onclick = async () => {
        try {
          const detail = await apiRequest(`/api/nodes/${nodeId}/operations/${op.id}`);
          if (!detail.ok) throw new Error("Operation detail unavailable");
          const record = await detail.json();
          if (epoch === getSelectionEpoch()) {
            displayOperationResult(record);
          }
        } catch (err) {
          showAlert(err.message, "danger");
        }
      };
      listContainer.appendChild(item);
    });

    // Auto-display latest operation result on fresh selection
    const resultBox = document.getElementById("op-result-box");
    if (offset === 0 && ops.length > 0 && resultBox && resultBox.style.display === "none") {
      apiRequest(`/api/nodes/${nodeId}/operations/${ops[0].id}`).then(async res => {
        if (res.ok && epoch === getSelectionEpoch()) {
          const latestRec = await res.json();
          displayOperationResult(latestRec);
        }
      }).catch(() => {});
    }

    // Pagination navigation bar
    const nav = document.createElement("div");
    nav.className = "history-nav";

    const prevBtn = document.createElement("button");
    prevBtn.type = "button";
    prevBtn.textContent = "← Previous";
    prevBtn.className = "btn btn-secondary btn-sm";
    prevBtn.disabled = (offset === 0);
    prevBtn.onclick = () => {
      setHistoryOffset(Math.max(0, offset - 20));
      fetchNodeOperationsHistory(nodeId);
    };
    nav.appendChild(prevBtn);

    const pageLabel = document.createElement("span");
    pageLabel.textContent = `Offset ${offset}–${offset + ops.length}`;
    nav.appendChild(pageLabel);

    const nextBtn = document.createElement("button");
    nextBtn.type = "button";
    nextBtn.textContent = "Next →";
    nextBtn.className = "btn btn-secondary btn-sm";
    nextBtn.disabled = (ops.length < 20 || offset >= 100000);
    nextBtn.onclick = () => {
      setHistoryOffset(offset + 20);
      fetchNodeOperationsHistory(nodeId);
    };
    nav.appendChild(nextBtn);

    listContainer.appendChild(nav);
  } catch (err) {
    if (epoch === getSelectionEpoch() && sequence === getHistorySequence()) {
      listContainer.textContent = "History unavailable: " + err.message;
    }
  }
}
