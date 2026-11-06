/**
 * Controlled Remote Operations Execution and Output Inspector.
 */

import {
  getSelectedNodeId,
  getSelectionEpoch
} from "./state.js";
import { apiRequest, showAlert } from "./api.js";
import { fetchNodeOperationsHistory } from "./history.js";

export function initOperations() {
  const actionSelect = document.getElementById("action-select");
  const diskContainer = document.getElementById("arg-disk-container");
  const svcContainer = document.getElementById("arg-service-container");
  const fixedNote = document.getElementById("arg-note-fixed");
  const execForm = document.getElementById("execute-op-form");
  const copyOutputBtn = document.getElementById("copy-output-btn");

  // Toggle dynamic argument inputs based on selected allowlisted action
  if (actionSelect) {
    actionSelect.addEventListener("change", (e) => {
      const action = e.target.value;
      if (diskContainer) diskContainer.style.display = (action === "system.disk") ? "block" : "none";
      if (svcContainer) svcContainer.style.display = (action === "service.status") ? "block" : "none";
      if (fixedNote) fixedNote.style.display = (action === "system.uptime" || action === "system.memory") ? "block" : "none";
    });
  }

  // Handle operation execution form submission
  if (execForm) {
    execForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const targetNodeId = getSelectedNodeId();
      if (!targetNodeId) return;

      const epoch = getSelectionEpoch();
      const action = actionSelect ? actionSelect.value : "system.uptime";
      const argumentsObj = {};

      if (action === "system.disk") {
        const diskInput = document.getElementById("arg-disk-path");
        argumentsObj["path"] = (diskInput ? diskInput.value : "").trim() || "/";
      } else if (action === "service.status") {
        const svcInput = document.getElementById("arg-service-name");
        argumentsObj["service_name"] = (svcInput ? svcInput.value : "").trim() || "ssh";
      }

      const execBtn = document.getElementById("exec-btn");
      if (execBtn) {
        execBtn.disabled = true;
        execBtn.innerHTML = '<span class="spinner"></span> Executing remotely over SSH...';
      }

      try {
        const res = await apiRequest(`/api/nodes/${targetNodeId}/operations`, {
          method: "POST",
          body: JSON.stringify({ action, arguments: argumentsObj })
        });

        const data = await res.json();
        if (res.ok) {
          if (getSelectedNodeId() === targetNodeId && getSelectionEpoch() === epoch) {
            displayOperationResult(data);
            fetchNodeOperationsHistory(targetNodeId);
          } else {
            showAlert(`Operation ${data.id} on node ${targetNodeId}: ${data.outcome}`, "info");
          }
        } else {
          showAlert(`Operation failed: ${data.error ? `${data.error.message} ${data.error.operation_id || ''} (node ${targetNodeId})` : 'Execution error'}`, "danger");
        }
      } catch (err) {
        showAlert("Operation request failed: " + err.message, "danger");
      } finally {
        if (execBtn) {
          execBtn.disabled = false;
          execBtn.innerHTML = '<svg class="icon" aria-hidden="true"><use href="/static/icons.svg#play"></use></svg><span>Execute Remote Operation</span>';
        }
      }
    });
  }

  // Copy terminal output to clipboard
  if (copyOutputBtn) {
    copyOutputBtn.addEventListener("click", () => {
      const stdout = (document.getElementById("result-stdout")?.textContent) || "";
      const stderr = (document.getElementById("result-stderr")?.textContent) || "";
      const combined = stderr ? `STDOUT:\n${stdout}\n\nSTDERR:\n${stderr}` : stdout;

      if (typeof navigator !== "undefined" && navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
        navigator.clipboard.writeText(combined).then(() => {
          copyOutputBtn.textContent = "Copied!";
          setTimeout(() => { copyOutputBtn.textContent = "Copy"; }, 2000);
        }).catch(() => {});
      }
    });
  }
}

/**
 * Display operation execution result safely with pure textContent.
 * Prevents stale result presentation across node switches.
 */
export function displayOperationResult(rec) {
  if (rec.node_id !== getSelectedNodeId()) return;

  const box = document.getElementById("op-result-box");
  if (box) box.style.display = "block";

  const badge = document.getElementById("result-outcome-badge");
  if (badge) {
    badge.textContent = rec.outcome;
    badge.className = `status-badge badge-${(rec.outcome || "").toLowerCase()}`;
  }

  const exitCodeSpan = document.getElementById("result-exit-code");
  if (exitCodeSpan) {
    exitCodeSpan.textContent = (rec.exit_code !== null && rec.exit_code !== undefined) ? `Exit Code: ${rec.exit_code}` : "Exit Code: —";
  }

  const truncTag = document.getElementById("result-truncated-tag");
  if (truncTag) {
    truncTag.style.display = rec.output_truncated ? "inline-block" : "none";
  }

  const uncertainWarning = document.getElementById("result-uncertain-warning");
  if (uncertainWarning) {
    uncertainWarning.style.display = (rec.outcome === "UNCERTAIN") ? "block" : "none";
  }

  const stdoutPre = document.getElementById("result-stdout");
  if (stdoutPre) {
    stdoutPre.textContent = rec.stdout ? rec.stdout : "(no standard output)";
  }

  const stderrSec = document.getElementById("result-stderr-section");
  const stderrPre = document.getElementById("result-stderr");
  if (rec.stderr && rec.stderr.trim()) {
    if (stderrPre) stderrPre.textContent = rec.stderr;
    if (stderrSec) stderrSec.style.display = "block";
  } else {
    if (stderrSec) stderrSec.style.display = "none";
  }

  const meta = document.getElementById("result-metadata");
  if (meta) {
    const completedTime = rec.completed_at ? new Date(rec.completed_at).toLocaleTimeString() : "in-progress";
    const digest = (rec.audit_metadata && rec.audit_metadata.operator_digest_prefix) ? rec.audit_metadata.operator_digest_prefix : "local";
    meta.textContent = `Node: ${rec.node_id} | Job ID: ${rec.id} | Completed: ${completedTime} | Operator: ${digest}`;
  }
}
