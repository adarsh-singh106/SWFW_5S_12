/**
 * Real SSH Node Onboarding Lifecycle Management.
 * Guides operators through:
 * 1. Inventory Registration
 * 2. Server Identity (Host-Key Fingerprint Out-of-band Verification & Deliberate Trust)
 * 3. Client Authentication (Operator Public Key Bootstrap into authorized_keys)
 * 4. SSH Verification (Handshake, Host Key, Auth, Command Execution Readiness)
 * 5. Operational Readiness Transition
 */

import { apiRequest } from "./api.js";
import { fetchFleetStatus } from "./fleet.js";
import { activateDialog, deactivateDialog, isTopDialog } from "./dialog-ownership.js";

let _activeOnboardingNode = null;
let generation = 0;
let scan = null;
let scanRevision = 0;
let details = null;
let validation = null;

const byId = id => document.getElementById(id);
const setupText = {
  READY: "Current configuration previously passed SSH authentication; check connectivity separately.",
  HOST_KEY_REQUIRED: "Host key trust required",
  AUTHENTICATION_REQUIRED: "SSH authentication needs attention",
  CONFIGURATION_ERROR: "SSH configuration needs attention",
  PENDING_SETUP: "SSH authentication has not been verified for this configuration"
};
const connectivityText = {
  REACHABLE: "Latest observation: SSH connected",
  UNREACHABLE: "Latest observation: connection unavailable",
  CHECK_ERROR: "Latest observation: SSH check error",
  STALE: "Latest observation expired",
  NOT_CHECKED: "No connectivity observation yet"
};
const guidance = {
  HOST_KEY_UNKNOWN: "Scan the host key and independently verify its fingerprint before trust.",
  HOST_KEY_MISMATCH: "The key presented by this endpoint differs from the currently trusted fingerprint. Rescan if the endpoint may have changed; if the mismatch persists, stop and request administrative review. Never trust a mismatched key here.",
  AUTH_FAILED: "Check the configured SSH user and target authorized_keys, then retry.",
  CONNECTION_REFUSED: "Check the target SSH service and port, then retry.",
  CONNECTION_TIMEOUT: "Check endpoint routing or firewall access, then retry.",
  DNS_ERROR: "Check the registered hostname and DNS resolution, then retry.",
  TIMEOUT: "SSH did not complete within its phase timeout; review the endpoint and retry.",
  EXECUTION_TIMEOUT: "The bounded check timed out; review the endpoint before retrying.",
  UNKNOWN_ERROR: "Review SSH configuration and server logs before retrying."
};

function owns(id, epoch) { return _activeOnboardingNode?.id === id && generation === epoch; }

function announce(message) { byId("onboarding-announcement").textContent = message; }
function errorMessage(message) {
  const box = byId("onboarding-feedback");
  box.textContent = message;
  box.style.display = "block";
  announce(message);
  if (isTopDialog(byId("onboarding-modal"))) box.focus();
}
function clearError() { byId("onboarding-feedback").style.display = "none"; byId("onboarding-feedback").textContent = ""; }
function resetScan() {
  ++scanRevision;
  scan = null;
  byId("fingerprint-acknowledgement").checked = false;
  byId("fingerprint-acknowledgement").disabled = true;
  byId("step-trust-btn").disabled = true;
  byId("step-fp-box").style.display = "none";
  byId("scanned-fingerprint-content").textContent = "";
  byId("scan-verification-instruction").textContent = "";
}
function trustAllowed() {
  return scan && scan.nodeId === _activeOnboardingNode?.id &&
    byId("fingerprint-acknowledgement").checked &&
    byId("scanned-fingerprint-content").textContent === scan.fingerprint &&
    scan.revision === scanRevision && scan.trust_state === "UNTRUSTED";
}
function updateTrust() { byId("step-trust-btn").disabled = !trustAllowed(); }
function setStep(id) {
  for (const step of ["step-register", "step-identity", "step-auth", "step-validate", "step-complete-box"]) {
    const element = byId(step);
    element.classList.toggle("active", step === id);
    if (step === id) element.setAttribute("aria-current", "step");
    else element.removeAttribute("aria-current");
  }
  byId("onboarding-progress").textContent = `${({"step-identity":"2", "step-auth":"3", "step-validate":"4", "step-complete-box":"5"})[id] || "1"} of 5 · ${({"step-identity":"Verify identity", "step-auth":"Configure authentication", "step-validate":"Check connectivity", "step-complete-box":"Review status"})[id] || "Registered"}`;
}
function chooseStep(data) {
  const state = data.setup_state;
  const mismatch = data.server_identity?.trust_state === "MISMATCH";
  if (mismatch || state === "HOST_KEY_REQUIRED") return "step-identity";
  if (state === "AUTHENTICATION_REQUIRED") return "step-auth";
  if (state === "CONFIGURATION_ERROR" || state === "READY") return "step-complete-box";
  return data.server_identity?.trust_state === "TRUSTED" ? "step-validate" : "step-identity";
}
function updatePrimary(step) {
  const primary = byId("onboarding-primary-btn");
  if (step === "step-identity") { primary.textContent = "Scan server host key"; primary.onclick = () => scanHostKey(_activeOnboardingNode.id); primary.disabled = false; }
  else if (step === "step-auth") { primary.textContent = "Check SSH connectivity"; primary.onclick = () => checkSSH(_activeOnboardingNode.id, generation); primary.disabled = false; }
  else if (step === "step-validate") { primary.textContent = "Check SSH connectivity"; primary.onclick = () => checkSSH(_activeOnboardingNode.id, generation); primary.disabled = false; }
  else { primary.textContent = "Refresh setup state"; primary.onclick = () => loadDetails(_activeOnboardingNode.id, generation); primary.disabled = false; }
}
function renderDetails(data, observation) {
  details = data;
  const identity = data.server_identity || {};
  const trusted = identity.presented_fingerprint;
  byId("trusted-fingerprint-content").textContent = trusted || "None currently trusted";
  byId("onboarding-ssh-user").textContent = data.client_authentication?.ssh_username || "Unavailable";
  byId("bootstrap-cmd-snippet").textContent = data.client_authentication?.bootstrap_instruction || "Configuration unavailable";
  byId("step-auth-box").style.display = "block";
  byId("onboarding-setup-state").textContent = setupText[data.setup_state] || data.setup_state || "Unavailable";
  byId("onboarding-connectivity-state").textContent = connectivityText[data.display_status] || "Connectivity state unavailable";
  const observed = observation?.observed_at;
  byId("onboarding-observation").textContent = observed ? `${observation.outcome} · ${new Date(observed).toLocaleString()}` : "No observation available";
  byId("onboarding-blocking-reason").textContent = data.blocking_reason || "";
  if (!validation && observation?.outcome === "CONNECTED") byId("validation-result").textContent = `Last reported SSH connection: ${new Date(observed).toLocaleString()}. Check freshness separately.`;
  const step = chooseStep(data);
  setStep(step); updatePrimary(step);
  byId("scan-host-key-btn").disabled = false;
  if (identity.trust_state === "MISMATCH") errorMessage(guidance.HOST_KEY_MISMATCH);
  else announce(`${byId("onboarding-progress").textContent}. ${byId("onboarding-setup-state").textContent}`);
}

export async function openOnboardingModal(node) {
  _activeOnboardingNode = node;
  const epoch = ++generation;
  resetScan(); clearError(); details = null; validation = null;
  byId("validation-result").textContent = "No check run in this session.";
  byId("trusted-fingerprint-content").textContent = "Loading";
  byId("onboarding-setup-state").textContent = "Loading";
  byId("onboarding-connectivity-state").textContent = "Loading";
  byId("onboarding-observation").textContent = "Loading";
  const modal = document.getElementById("onboarding-modal");
  activateDialog(modal);
  modal.style.display = "flex";
  document.getElementById("onboarding-node-title").textContent = `${node.name} (${node.address}:${node.ssh_port})`;
  setStep("step-identity");
  if (isTopDialog(modal)) byId("close-onboarding-btn").focus();
  modal.onkeydown = event => {
    if (event.key === "Escape") { event.preventDefault(); closeOnboardingModal(); return; }
    if (event.key !== "Tab") return;
    const controls = Array.from(modal.querySelectorAll("button, input, [tabindex]"))
      .filter(el => !el.disabled && el.offsetParent !== null && el.tabIndex !== -1);
    if (!controls.length) return;
    const first = controls[0], last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  };
  await loadDetails(node.id, epoch);
}

export function closeOnboardingModal() {
  ++generation;
  _activeOnboardingNode = null;
  resetScan(); clearError(); details = null; validation = null;
  const modal = document.getElementById("onboarding-modal");
  modal.style.display = "none";
  deactivateDialog(modal);
}

async function loadDetails(id, epoch) {
  try {
    const response = await apiRequest(`/api/nodes/${id}/onboarding`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error?.message || data.detail || "Onboarding status unavailable");
    const latest = await apiRequest(`/api/nodes/${id}/connectivity`);
    const recent = await latest.json();
    if (!owns(id, epoch)) return;
    if (!latest.ok) throw new Error(recent.error?.message || recent.detail || "Latest connectivity unavailable");
    clearError();
    if (isTopDialog(byId("onboarding-modal")) && !document.getElementById("onboarding-modal").contains?.(document.activeElement)) {
      document.getElementById("close-onboarding-btn").focus();
    }
    renderDetails(data, recent.observation);
    document.getElementById("scan-host-key-btn").onclick = () => scanHostKey(id);
    document.getElementById("onboarding-check-ssh-btn").onclick = () => checkSSH(id, epoch);
  } catch (error) {
    if (owns(id, epoch)) { errorMessage(`${error.message}. Retry loading setup.`); updatePrimary("step-complete-box"); }
  }
}

async function checkSSH(id, epoch) {
  if (!owns(id, epoch)) return;
  clearError(); setStep("step-validate"); updatePrimary("step-validate");
  const button = byId("onboarding-check-ssh-btn");
  const primary = byId("onboarding-primary-btn");
  button.disabled = true; primary.disabled = true;
  byId("validation-result").textContent = "Checking SSH connectivity…";
  announce("Checking SSH connectivity");
  try {
    const response = await apiRequest(`/api/nodes/${id}/connectivity-check`, {method: "POST"});
    const result = await response.json();
    if (!owns(id, epoch)) return;
    if (!response.ok) throw new Error(result.error?.message || result.detail || "SSH check request failed");
    validation = result;
    const category = result.error_category || result.outcome || "UNKNOWN_ERROR";
    byId("validation-result").textContent = result.outcome === "CONNECTED"
      ? `SSH connected at ${new Date(result.observed_at).toLocaleString()}. Current connectivity freshness is shown below.`
      : `SSH check failed: ${category}. ${guidance[category] || "Review the endpoint and retry."}`;
    announce(byId("validation-result").textContent);
    await loadDetails(id, epoch);
    if (owns(id, epoch)) { setStep("step-validate"); updatePrimary("step-validate"); }
  } catch (error) {
    if (owns(id, epoch)) { byId("validation-result").textContent = "SSH check could not complete; outcome may be unknown."; errorMessage(`${error.message}. Review the endpoint before retrying.`); }
  } finally {
    if (owns(id, epoch)) { button.disabled = false; primary.disabled = false; fetchFleetStatus(); }
  }
}

export async function scanHostKey(id) {
  const epoch = generation;
  if (!owns(id, epoch)) return;
  const button = document.getElementById("scan-host-key-btn");
  resetScan(); clearError();
  const revision = scanRevision;
  button.disabled = true;
  byId("onboarding-primary-btn").disabled = true;
  announce("Scanning server host key");
  try {
    const response = await apiRequest(`/api/nodes/${id}/scan-host-key`, {method: "POST"});
    const data = await response.json();
    if (!owns(id, epoch) || revision !== scanRevision) return;
    if (!response.ok) throw new Error(data.error?.message || data.detail || "Host scan failed");
    if (!data.fingerprint || !data.confirmation) throw new Error("Host scan returned incomplete identity data");
    if (data.trust_state !== "UNTRUSTED" && data.trust_state !== "MISMATCH") {
      throw new Error("This key is already trusted or cannot be enrolled. Review setup state");
    }
    scan = { ...data, nodeId: id, revision };
    byId("scanned-fingerprint-content").textContent = data.fingerprint;
    byId("scan-verification-instruction").textContent = data.verification_instruction || "Verify the fingerprint independently on the target console";
    byId("step-fp-box").style.display = "block";
    if (data.trust_state === "MISMATCH") {
      setStep("step-identity"); updatePrimary("step-identity");
      byId("step-trust-btn").style.display = "none";
      errorMessage(guidance.HOST_KEY_MISMATCH);
    } else {
      byId("fingerprint-acknowledgement").disabled = false;
      byId("step-trust-btn").style.display = "inline-flex";
      byId("step-trust-btn").onclick = () => trustHostKey(id, data.fingerprint, data.confirmation, epoch, revision);
      announce("Untrusted key presented by server. Compare its fingerprint through a trusted channel before acknowledging.");
    }
  } catch (error) { if (owns(id, epoch) && revision === scanRevision) { resetScan(); errorMessage(error.message); } }
  finally {
    if (owns(id, epoch)) {
      button.disabled = false;
      byId("onboarding-primary-btn").disabled = false;
      const modal = document.getElementById("onboarding-modal");
      if (modal && !modal.contains(document.activeElement)) {
        button.focus();
      }
    }
  }
}

export async function trustHostKey(id, fingerprint, confirmation, epoch = generation, revision = scanRevision) {
  if (!owns(id, epoch) || revision !== scanRevision || !trustAllowed() || fingerprint !== scan.fingerprint || confirmation !== scan.confirmation) return;
  const button = document.getElementById("step-trust-btn");
  button.disabled = true;
  try {
    const result = await apiRequest(`/api/nodes/${id}/trust-host-key`, {
      method: "POST", body: JSON.stringify({fingerprint, confirmation})
    });
    const data = await result.json();
    if (!owns(id, epoch) || revision !== scanRevision) return;
    if (!result.ok) throw new Error(data.error?.message || data.detail || "Enrollment rejected");
    resetScan();
    await loadDetails(id, epoch);
  } catch (error) { if (owns(id, epoch)) { resetScan(); errorMessage(`${error.message}. Rescan or request administrative review.`); } }
  finally { if (owns(id, epoch)) button.disabled = !trustAllowed(); }
}

export function initOnboarding() {
  const toggleBtn = document.getElementById("toggle-register-btn");
  const drawer = document.getElementById("register-drawer");
  const form = document.getElementById("register-form");

  if (toggleBtn && drawer) {
    toggleBtn.addEventListener("click", () => {
      const isVisible = drawer.style.display !== "none";
      drawer.style.display = isVisible ? "none" : "block";
      if (!isVisible) {
        const input = document.getElementById("node-name");
        if (input && typeof input.focus === "function") input.focus();
      }
    });
  }

  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const nameInput = document.getElementById("node-name");
      const addrInput = document.getElementById("node-address");
      const portInput = document.getElementById("node-port");
      const feedback = document.getElementById("register-feedback");
      const btn = document.getElementById("register-btn");

      const name = (nameInput.value || "").trim();
      const address = (addrInput.value || "").trim();
      const port = parseInt(portInput.value || "22", 10);

      btn.disabled = true;
      btn.textContent = "Registering node…";
      feedback.textContent = "Registering node in inventory…";
      feedback.style.display = "block";

      try {
        const res = await apiRequest("/api/nodes", {
          method: "POST",
          body: JSON.stringify({ name, address, ssh_port: port })
        });

        const data = await res.json();
        if (res.status === 201) {
          feedback.textContent = `Node added to inventory. SSH connectivity has not yet been verified. Opening setup for ${name} (ID ${data.id}).`;
          feedback.style.color = "var(--success-text)";
          feedback.style.display = "block";
          nameInput.value = "";
          addrInput.value = "";
          portInput.value = "22";
          fetchFleetStatus();

          setTimeout(() => {
            drawer.style.display = "none";
            openOnboardingModal({ id: data.id, name, address, ssh_port: port });
          }, 800);
        } else {
          feedback.textContent = `${data.error?.message || "Registration failed."} Review the fields and retry.`;
          feedback.style.color = "var(--danger-text)";
          feedback.style.display = "block";
        }
      } catch (err) {
        feedback.textContent = `Registration failed: ${err.message}. Review the fields and retry.`;
        feedback.style.color = "var(--danger-text)";
        feedback.style.display = "block";
      } finally {
        btn.disabled = false;
        btn.textContent = "Register";
      }
    });
  }

  // Setup modal close handler
  const closeBtn = document.getElementById("close-onboarding-btn");
  if (closeBtn) {
    closeBtn.addEventListener("click", closeOnboardingModal);
  }
  byId("close-onboarding-footer-btn").addEventListener("click", closeOnboardingModal);
  byId("fingerprint-acknowledgement").addEventListener("change", updateTrust);
}

