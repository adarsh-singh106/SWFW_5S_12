/**
 * Controlled Remote Operations Execution and Output Inspector.
 */

import {
  getSelectedNodeId,
  getSelectionEpoch,
  getInventoryReturnFocus
} from "./state.js";
import { apiRequest, showAlert } from "./api.js";
import { fetchNodeOperationsHistory } from "./history.js";

const inFlightByNode = new Map();
const latestResultByNode = new Map();
const ACTION_RADIO_IDS = ["action-uptime", "action-memory", "action-disk", "action-service"];

/**
 * Live accessible announcements for screen readers.
 */
export function announce(text) {
  const announcer = document.getElementById("workbench-announcer");
  if (announcer) {
    announcer.textContent = text;
  }
}

/**
 * Get the currently selected action radio element.
 */
export function getSelectedActionRadio() {
  for (const id of ACTION_RADIO_IDS) {
    const el = document.getElementById(id);
    if (el && el.checked) return el;
  }
  return document.getElementById("action-uptime");
}

/**
 * Validate filesystem path against backend catalog constraints:
 * - string, 1 to 255 chars
 * - absolute POSIX path starting with '/'
 * - no whitespace
 * - pattern: ^/[a-zA-Z0-9_\-\./]*$
 * - no '..' path traversal segments
 */
export function validateDiskPath(raw) {
  const path = (raw || "").trim();
  if (!path) {
    return { valid: false, error: "Filesystem path is required", value: "" };
  }
  if (path.length > 255) {
    return { valid: false, error: "Path must not exceed 255 characters", value: path };
  }
  if (!path.startsWith("/")) {
    return { valid: false, error: "Path must be an absolute POSIX path starting with '/'", value: path };
  }
  if (/\s/.test(path)) {
    return { valid: false, error: "Path must not contain whitespace", value: path };
  }
  if (!/^\/[a-zA-Z0-9_\-\./]*$/.test(path)) {
    return { valid: false, error: "Path contains invalid characters (allowed: a-z, A-Z, 0-9, _, -, ., /)", value: path };
  }
  if (path.split("/").includes("..")) {
    return { valid: false, error: "Path must not contain directory traversal ('..')", value: path };
  }
  return { valid: true, error: null, value: path };
}

/**
 * Validate systemd service unit name against backend catalog constraints:
 * - string, 1 to 64 chars
 * - must not start with a hyphen
 * - no whitespace
 * - pattern: ^[a-zA-Z0-9_\-\.@]{1,64}$
 */
export function validateServiceName(raw) {
  const name = (raw || "").trim();
  if (!name) {
    return { valid: false, error: "Service unit name is required", value: "" };
  }
  if (name.length > 64) {
    return { valid: false, error: "Service name must not exceed 64 characters", value: name };
  }
  if (name.startsWith("-")) {
    return { valid: false, error: "Service name must not start with a hyphen", value: name };
  }
  if (/\s/.test(name)) {
    return { valid: false, error: "Service name must not contain whitespace", value: name };
  }
  if (!/^[a-zA-Z0-9_\-\.@]{1,64}$/.test(name)) {
    return { valid: false, error: "Service name contains invalid characters (allowed: alphanumeric, _, -, ., @)", value: name };
  }
  return { valid: true, error: null, value: name };
}

/**
 * Generate preview of exact compiled command matching backend catalog.
 */
export function getCommandPreview(action, diskPath, serviceName) {
  if (action === "system.uptime") {
    return "uptime";
  }
  if (action === "system.memory") {
    return "free -m";
  }
  if (action === "system.disk") {
    const v = validateDiskPath(diskPath);
    return v.valid ? `df -h -P -- ${v.value}` : "df -h -P -- [invalid path]";
  }
  if (action === "service.status") {
    const v = validateServiceName(serviceName);
    return v.valid ? `systemctl --no-pager status -- ${v.value}` : "systemctl --no-pager status -- [invalid service]";
  }
  return "uptime";
}

/**
 * Update the read-only live command preview display.
 */
export function updateCommandPreview() {
  const actionRadio = getSelectedActionRadio();
  const action = actionRadio ? actionRadio.value : "system.uptime";
  const diskInput = document.getElementById("arg-disk-path");
  const svcInput = document.getElementById("arg-service-name");
  const previewCode = document.getElementById("command-preview-text");

  const preview = getCommandPreview(
    action,
    diskInput ? diskInput.value : "/",
    svcInput ? svcInput.value : "ssh"
  );
  if (previewCode) {
    previewCode.textContent = preview;
  }
}

/**
 * Calculate recorded execution duration strictly from valid started_at and completed_at timestamps.
 */
export function formatDuration(startedAt, completedAt) {
  if (!startedAt || !completedAt) return "—";
  const start = new Date(startedAt).getTime();
  const end = new Date(completedAt).getTime();
  if (isNaN(start) || isNaN(end) || end < start) return "—";
  const ms = end - start;
  if (ms < 1000) {
    return `${ms}ms`;
  }
  return `${(ms / 1000).toFixed(2)}s`;
}

export function isNodeInFlight(nodeId) {
  return Boolean(inFlightByNode.get(nodeId));
}

export function getLatestNodeResult(nodeId) {
  return latestResultByNode.get(nodeId) || null;
}

/**
 * Update dispatch button state specifically for the current node.
 */
export function updateExecButtonState(nodeId) {
  const execBtn = document.getElementById("exec-btn");
  const execLabel = document.getElementById("exec-btn-label");
  if (!execBtn) return;

  const inFlight = isNodeInFlight(nodeId);
  execBtn.disabled = inFlight;
  if (inFlight) {
    if (execLabel) execLabel.textContent = "Executing remotely over SSH...";
  } else {
    if (execLabel) execLabel.textContent = "Execute Remote Operation";
  }
}

/**
 * Show standby placeholder state in the Result Inspector.
 */
export function showStandbyInspector() {
  const standby = document.getElementById("inspector-standby");
  const resultBox = document.getElementById("op-result-box");
  const modeTag = document.getElementById("inspector-mode-tag");
  const badge = document.getElementById("result-outcome-badge");
  const admittedAlert = document.getElementById("result-admitted-alert");

  if (standby) standby.style.display = "block";
  if (resultBox) resultBox.style.display = "none";
  if (admittedAlert) admittedAlert.style.display = "none";
  if (modeTag) {
    modeTag.textContent = "Awaiting Execution";
    modeTag.className = "tag tag-mode";
  }
  if (badge) {
    badge.textContent = "STANDBY";
    badge.className = "status-badge badge-not_checked";
  }
}

/**
 * Initialize Operations Console controls, listeners, and preview.
 */
export function initOperations() {
  const execForm = document.getElementById("execute-op-form");
  const copyOutputBtn = document.getElementById("copy-output-btn");
  const diskContainer = document.getElementById("arg-disk-container");
  const svcContainer = document.getElementById("arg-service-container");
  const fixedNote = document.getElementById("arg-note-fixed");
  const diskInput = document.getElementById("arg-disk-path");
  const svcInput = document.getElementById("arg-service-name");
  const diskError = document.getElementById("arg-disk-error");
  const svcError = document.getElementById("arg-service-error");
  const returnBtn = document.getElementById("return-to-inventory-btn");

  function switchAction(action) {
    // Synchronize backwards-compatible hidden select if present
    const actionSelect = document.getElementById("action-select");
    if (actionSelect) actionSelect.value = action;

    const isDisk = (action === "system.disk");
    const isSvc = (action === "service.status");
    const isFixed = (action === "system.uptime" || action === "system.memory");

    if (diskContainer) diskContainer.style.display = isDisk ? "block" : "none";
    if (svcContainer) svcContainer.style.display = isSvc ? "block" : "none";
    if (fixedNote) fixedNote.style.display = isFixed ? "flex" : "none";

    // Disable hidden inputs so native browser validation never fails on hidden fields
    if (diskInput) {
      diskInput.disabled = !isDisk;
      if (!isDisk && diskError) {
        diskError.textContent = "";
        diskInput.removeAttribute("aria-invalid");
      }
    }
    if (svcInput) {
      svcInput.disabled = !isSvc;
      if (!isSvc && svcError) {
        svcError.textContent = "";
        svcInput.removeAttribute("aria-invalid");
      }
    }

    updateCommandPreview();
  }

  // Radio button listeners using ACTION_RADIO_IDS
  ACTION_RADIO_IDS.forEach(id => {
    const radio = document.getElementById(id);
    if (radio) {
      radio.addEventListener("change", () => {
        if (radio.checked) {
          switchAction(radio.value);
        }
      });
    }
  });

  // Dynamic argument validation on input
  if (diskInput) {
    diskInput.addEventListener("input", () => {
      const v = validateDiskPath(diskInput.value);
      if (diskError) {
        diskError.textContent = v.valid ? "" : v.error;
      }
      diskInput.setAttribute("aria-invalid", v.valid ? "false" : "true");
      updateCommandPreview();
    });
  }

  if (svcInput) {
    svcInput.addEventListener("input", () => {
      const v = validateServiceName(svcInput.value);
      if (svcError) {
        svcError.textContent = v.valid ? "" : v.error;
      }
      svcInput.setAttribute("aria-invalid", v.valid ? "false" : "true");
      updateCommandPreview();
    });
  }

  // Initial preview setup
  const initialChecked = getSelectedActionRadio();
  switchAction(initialChecked ? initialChecked.value : "system.uptime");

  // Form submission handler
  if (execForm) {
    execForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const targetNodeId = getSelectedNodeId();
      if (!targetNodeId) return;

      if (isNodeInFlight(targetNodeId)) {
        showAlert("An operation is already in flight for this node.", "warning");
        return;
      }

      const epoch = getSelectionEpoch();
      const actionRadio = getSelectedActionRadio();
      const action = actionRadio ? actionRadio.value : "system.uptime";
      const argumentsObj = {};

      // Client-side validation before dispatch
      if (action === "system.disk") {
        const v = validateDiskPath(diskInput ? diskInput.value : "");
        if (!v.valid) {
          if (diskError) diskError.textContent = v.error;
          if (diskInput) {
            diskInput.setAttribute("aria-invalid", "true");
            diskInput.focus();
          }
          announce(`Validation error: ${v.error}`);
          return;
        }
        if (diskError) diskError.textContent = "";
        argumentsObj["path"] = v.value;
      } else if (action === "service.status") {
        const v = validateServiceName(svcInput ? svcInput.value : "");
        if (!v.valid) {
          if (svcError) svcError.textContent = v.error;
          if (svcInput) {
            svcInput.setAttribute("aria-invalid", "true");
            svcInput.focus();
          }
          announce(`Validation error: ${v.error}`);
          return;
        }
        if (svcError) svcError.textContent = "";
        argumentsObj["service_name"] = v.value;
      }

      // Mark in-flight for this specific target node
      inFlightByNode.set(targetNodeId, true);
      updateExecButtonState(targetNodeId);
      announce(`Executing ${action} on node ${targetNodeId} over SSH...`);

      const admittedAlert = document.getElementById("result-admitted-alert");
      if (admittedAlert) admittedAlert.style.display = "none";

      try {
        const res = await apiRequest(`/api/nodes/${targetNodeId}/operations`, {
          method: "POST",
          body: JSON.stringify({ action, arguments: argumentsObj })
        });

        const data = await res.json().catch(() => ({}));

        if (res.ok) {
          latestResultByNode.set(targetNodeId, data);
          if (getSelectedNodeId() === targetNodeId && getSelectionEpoch() === epoch) {
            displayOperationResult(data, false);
            announce(`Operation ${data.id} finished with outcome ${data.outcome}`);
            fetchNodeOperationsHistory(targetNodeId);
          } else {
            announce(`Operation on node ${targetNodeId} completed: ${data.outcome}`);
          }
        } else if (res.status === 409) {
          showAlert(`Operation conflict (409): An operation is already in flight for node ${targetNodeId}.`, "warning");
          announce("Execution rejected: operation already in flight");
        } else if (res.status === 429) {
          showAlert("Capacity limit reached (429): Maximum concurrent operations running. Please retry shortly.", "warning");
          announce("Execution rejected: control plane capacity reached");
        } else if (res.status === 503 && data.error && data.error.operation_id) {
          const opId = data.error.operation_id;
          if (admittedAlert && getSelectedNodeId() === targetNodeId && getSelectionEpoch() === epoch) {
            const msgEl = document.getElementById("result-admitted-msg");
            if (msgEl) {
              msgEl.textContent = `Admitted Operation Timeout: Operation ${opId} was admitted but response could not be confirmed before the deadline. Do not automatically replay.`;
            }
            admittedAlert.style.display = "block";
            const inspectBtn = document.getElementById("inspect-admitted-btn");
            if (inspectBtn) {
              inspectBtn.onclick = () => {
                apiRequest(`/api/nodes/${targetNodeId}/operations/${opId}`)
                  .then(r => r.json())
                  .then(rec => {
                    if (getSelectionEpoch() === epoch) displayOperationResult(rec, true);
                  })
                  .catch(err => showAlert(err.message, "danger"));
              };
            }
          }
          showAlert(`Operation ${opId} admitted but timeout occurred. Inspect audit history rather than replaying.`, "warning");
          announce(`Operation ${opId} timed out after admission`);
          fetchNodeOperationsHistory(targetNodeId);
        } else {
          const msg = data.error ? data.error.message : `HTTP ${res.status}`;
          showAlert(`Operation execution failed: ${msg}`, "danger");
          announce(`Operation execution failed: ${msg}`);
        }
      } catch (err) {
        showAlert(`Operation request failed: ${err.message}. Remote state is unknown; do not automatically re-execute.`, "danger");
        announce("Network error during operation dispatch; outcome unknown");
      } finally {
        inFlightByNode.set(targetNodeId, false);
        if (getSelectedNodeId() === targetNodeId) {
          updateExecButtonState(targetNodeId);
        }
      }
    });
  }

  // Copy output to clipboard with feedback
  if (copyOutputBtn) {
    copyOutputBtn.addEventListener("click", async () => {
      const stdout = document.getElementById("result-stdout")?.textContent || "";
      const stderrSec = document.getElementById("result-stderr-section");
      const stderr = (stderrSec && stderrSec.style.display !== "none")
        ? (document.getElementById("result-stderr")?.textContent || "")
        : "";
      const combined = stderr ? `STDOUT:\n${stdout}\n\nSTDERR:\n${stderr}` : stdout;
      const copyBtnText = document.getElementById("copy-btn-text") || copyOutputBtn;

      try {
        if (typeof navigator !== "undefined" && navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
          await navigator.clipboard.writeText(combined);
          copyBtnText.textContent = "Copied!";
          announce("Execution output copied to clipboard");
          setTimeout(() => { copyBtnText.textContent = "Copy Output"; }, 2000);
        } else {
          throw new Error("Clipboard API unavailable");
        }
      } catch {
        copyBtnText.textContent = "Copy Failed";
        announce("Failed to copy execution output");
        setTimeout(() => { copyBtnText.textContent = "Copy Output"; }, 2000);
      }
    });
  }

  // Return to inventory button
  if (returnBtn) {
    returnBtn.addEventListener("click", () => {
      const invCard = document.getElementById("inventory-card");
      const reducedMotion = typeof window !== "undefined" && window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (invCard) {
        invCard.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
      }
      const returnFocus = getInventoryReturnFocus();
      if (returnFocus && returnFocus.isConnected) {
        returnFocus.focus();
      } else if (invCard) {
        invCard.focus();
      }
      announce("Returned to inventory");
    });
  }
}

/**
 * Display operation execution result safely with pure textContent.
 * Supports distinguishing Live Execution from Historical Audit Records.
 */
export function displayOperationResult(rec, isHistorical = false) {
  if (!rec || rec.node_id !== getSelectedNodeId()) return;

  const standby = document.getElementById("inspector-standby");
  if (standby) standby.style.display = "none";

  const box = document.getElementById("op-result-box");
  if (box) box.style.display = "block";

  const admittedAlert = document.getElementById("result-admitted-alert");
  if (admittedAlert) admittedAlert.style.display = "none";

  // Mode Tag (Live vs Historical)
  const modeTag = document.getElementById("inspector-mode-tag");
  if (modeTag) {
    modeTag.textContent = isHistorical ? "Historical Record" : "Live Execution";
    modeTag.className = isHistorical ? "tag tag-historical" : "tag tag-live";
  }

  // Outcome Badge
  const badge = document.getElementById("result-outcome-badge");
  if (badge) {
    badge.textContent = rec.outcome || "UNKNOWN";
    badge.className = `status-badge badge-${(rec.outcome || "").toLowerCase()}`;
  }

  // Operation ID
  const opIdSpan = document.getElementById("result-op-id");
  if (opIdSpan) {
    opIdSpan.textContent = rec.id || "—";
  }

  // Target Node Context
  const nodeContextSpan = document.getElementById("result-node-context");
  if (nodeContextSpan) {
    nodeContextSpan.textContent = `Node #${rec.node_id}`;
  }

  // Action and Arguments Context
  const actionContextSpan = document.getElementById("result-action-context");
  if (actionContextSpan) {
    const argsStr = (rec.arguments && Object.keys(rec.arguments).length > 0)
      ? JSON.stringify(rec.arguments)
      : "none";
    actionContextSpan.textContent = `${rec.action} (${argsStr})`;
  }

  // Execution Duration
  const durationSpan = document.getElementById("result-duration");
  if (durationSpan) {
    durationSpan.textContent = formatDuration(rec.started_at, rec.completed_at);
  }

  // Exit Code
  const exitCodeSpan = document.getElementById("result-exit-code");
  if (exitCodeSpan) {
    exitCodeSpan.textContent = (rec.exit_code !== null && rec.exit_code !== undefined)
      ? `Exit Code: ${rec.exit_code}`
      : "Exit Code: —";
  }

  // Failure Category
  const failCatSpan = document.getElementById("result-failure-category");
  if (failCatSpan) {
    failCatSpan.textContent = rec.failure_category || "—";
  }

  // Timestamps
  const reqTime = document.getElementById("result-requested-at");
  if (reqTime) {
    reqTime.textContent = rec.requested_at ? new Date(rec.requested_at).toLocaleString() : "—";
  }
  const startTime = document.getElementById("result-started-at");
  if (startTime) {
    startTime.textContent = rec.started_at ? new Date(rec.started_at).toLocaleString() : "—";
  }
  const compTime = document.getElementById("result-completed-at");
  if (compTime) {
    compTime.textContent = rec.completed_at ? new Date(rec.completed_at).toLocaleString() : "—";
  }

  // Truncation Tag
  const truncTag = document.getElementById("result-truncated-tag");
  if (truncTag) {
    truncTag.style.display = rec.output_truncated ? "inline-block" : "none";
  }

  // Uncertain Warning Alert
  const uncertainWarning = document.getElementById("result-uncertain-warning");
  if (uncertainWarning) {
    uncertainWarning.style.display = (rec.outcome === "UNCERTAIN") ? "block" : "none";
  }

  // Standard Output
  const stdoutPre = document.getElementById("result-stdout");
  if (stdoutPre) {
    stdoutPre.textContent = (rec.stdout !== null && rec.stdout !== undefined && rec.stdout !== "")
      ? rec.stdout
      : "(no standard output)";
  }

  // Standard Error Stream (Rendered only when non-empty)
  const stderrSec = document.getElementById("result-stderr-section");
  const stderrPre = document.getElementById("result-stderr");
  if (rec.stderr && rec.stderr.trim()) {
    if (stderrPre) stderrPre.textContent = rec.stderr;
    if (stderrSec) stderrSec.style.display = "block";
  } else {
    if (stderrSec) stderrSec.style.display = "none";
  }

  // Terminal Meta Footer
  const meta = document.getElementById("result-metadata");
  if (meta) {
    const completedStr = rec.completed_at ? new Date(rec.completed_at).toLocaleTimeString() : "in-progress";
    const digest = (rec.audit_metadata && rec.audit_metadata.operator_digest_prefix)
      ? rec.audit_metadata.operator_digest_prefix
      : "local";
    meta.textContent = `Node: ${rec.node_id} | Job ID: ${rec.id} | Completed: ${completedStr} | Operator: ${digest}`;
  }
}
