/**
 * Real SSH Node Onboarding Lifecycle Management.
 * Guides operators through:
 * 1. Inventory Registration
 * 2. Server Identity (Host-Key Fingerprint Out-of-band Verification & Deliberate Trust)
 * 3. Client Authentication (Operator Public Key Bootstrap into authorized_keys)
 * 4. SSH Verification (Handshake, Host Key, Auth, Command Execution Readiness)
 * 5. Operational Readiness Transition
 */

import { apiRequest, showAlert } from "./api.js";
import { fetchFleetStatus } from "./fleet.js";

let _activeOnboardingNode = null;
let generation = 0;
let returnFocus = null;

function owns(id, epoch) { return _activeOnboardingNode?.id === id && generation === epoch; }

function resetWorkflow() {
  for (const id of ["step-fp-box", "step-trust-btn", "step-auth-box", "step-complete-box"]) {
    document.getElementById(id).style.display = "none";
  }
  for (const id of ["scan-host-key-btn", "step-trust-btn", "onboarding-check-ssh-btn"]) {
    const button = document.getElementById(id);
    button.onclick = null;
    button.disabled = false;
  }
  document.getElementById("scanned-fingerprint-content").textContent = "";
  document.getElementById("bootstrap-cmd-snippet").textContent = "";
}

export async function openOnboardingModal(node) {
  returnFocus = document.activeElement;
  _activeOnboardingNode = node;
  const epoch = ++generation;
  resetWorkflow();
  const modal = document.getElementById("onboarding-modal");
  modal.style.display = "flex";
  document.getElementById("onboarding-node-title").textContent = `${node.name} (${node.address}:${node.ssh_port})`;
  document.getElementById("close-onboarding-btn").focus();
  modal.onkeydown = event => {
    if (event.key === "Escape") { closeOnboardingModal(); return; }
    if (event.key !== "Tab") return;
    const controls = Array.from(modal.querySelectorAll("button, input, [tabindex]"))
      .filter(el => !el.disabled && el.offsetParent !== null);
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
  resetWorkflow();
  document.getElementById("onboarding-modal").style.display = "none";
  if (returnFocus?.isConnected) returnFocus.focus();
}

async function loadDetails(id, epoch) {
  try {
    const response = await apiRequest(`/api/nodes/${id}/onboarding`);
    if (!response.ok) throw new Error("Onboarding status unavailable");
    const data = await response.json();
    if (!owns(id, epoch)) return;
    resetWorkflow();
    if (!document.getElementById("onboarding-modal").contains?.(document.activeElement)) {
      document.getElementById("close-onboarding-btn").focus();
    }
    document.getElementById("step-fp-box").style.display = "block";
    document.getElementById("step-auth-box").style.display = "block";
    const identity = data.server_identity || {};
    document.getElementById("scanned-fingerprint-content").textContent =
      `Trust: ${identity.trust_state}\nTrusted fingerprint: ${identity.presented_fingerprint || "None"}\n${data.blocking_reason || ""}`;
    document.getElementById("bootstrap-cmd-snippet").textContent = data.client_authentication?.bootstrap_instruction || "Configuration error";
    document.getElementById("step-complete-box").style.display = data.setup_state === "READY" ? "block" : "none";
    document.getElementById("scan-host-key-btn").onclick = () => scanHostKey(id);
    document.getElementById("onboarding-check-ssh-btn").onclick = async () => {
      if (!owns(id, epoch)) return;
      const button = document.getElementById("onboarding-check-ssh-btn");
      button.disabled = true;
      document.getElementById("step-complete-box").style.display = "none";
      try {
        const result = await apiRequest(`/api/nodes/${id}/connectivity-check`, {method: "POST"});
        if (!result.ok) throw new Error("SSH validation failed");
        if (owns(id, epoch)) await loadDetails(id, epoch);
      } catch (error) { if (owns(id, epoch)) showAlert(error.message, "danger"); }
      finally { if (owns(id, epoch)) button.disabled = false; }
      fetchFleetStatus();
    };
  } catch (error) {
    if (owns(id, epoch)) {
      resetWorkflow();
      showAlert(error.message, "danger");
    }
  }
}

export async function scanHostKey(id) {
  const epoch = generation;
  if (!owns(id, epoch)) return;
  const button = document.getElementById("scan-host-key-btn");
  const trust = document.getElementById("step-trust-btn");
  button.disabled = true;
  trust.onclick = null;
  trust.style.display = "none";
  try {
    const response = await apiRequest(`/api/nodes/${id}/scan-host-key`, {method: "POST"});
    const data = await response.json();
    if (!owns(id, epoch)) return;
    if (!response.ok) throw new Error(data.error?.message || "Host scan failed");
    document.getElementById("scanned-fingerprint-content").textContent =
      `UNTRUSTED PRESENTED KEY\n${data.fingerprint}\n${data.verification_instruction || "Verify independently on the target console"}`;
    trust.style.display = "inline-flex";
    trust.onclick = () => trustHostKey(id, data.fingerprint, data.confirmation, epoch);
  } catch (error) { if (owns(id, epoch)) showAlert(error.message, "danger"); }
  finally { if (owns(id, epoch)) button.disabled = false; }
}

export async function trustHostKey(id, fingerprint, confirmation, epoch = generation) {
  if (!owns(id, epoch)) return;
  const button = document.getElementById("step-trust-btn");
  button.disabled = true;
  try {
    const result = await apiRequest(`/api/nodes/${id}/trust-host-key`, {
      method: "POST", body: JSON.stringify({fingerprint, confirmation})
    });
    if (!result.ok) throw new Error("Enrollment rejected; rescan or request administrative review");
    if (owns(id, epoch)) await loadDetails(id, epoch);
  } catch (error) { if (owns(id, epoch)) showAlert(error.message, "danger"); }
  finally { if (owns(id, epoch)) button.disabled = false; }
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
      btn.innerHTML = '<span class="spinner"></span>';

      try {
        const res = await apiRequest("/api/nodes", {
          method: "POST",
          body: JSON.stringify({ name, address, ssh_port: port })
        });

        const data = await res.json();
        if (res.status === 201) {
          feedback.textContent = `Node '${name}' (ID ${data.id}) registered in inventory. Opening guided onboarding...`;
          feedback.style.color = "var(--success-text)";
          feedback.style.display = "block";
          nameInput.value = "";
          addrInput.value = "";
          portInput.value = "22";
          fetchFleetStatus();

          setTimeout(() => {
            feedback.style.display = "none";
            drawer.style.display = "none";
            openOnboardingModal({ id: data.id, name, address, ssh_port: port });
          }, 800);
        } else {
          feedback.textContent = data.error ? data.error.message : "Registration failed.";
          feedback.style.color = "var(--danger-text)";
          feedback.style.display = "block";
        }
      } catch (err) {
        feedback.textContent = "Error: " + err.message;
        feedback.style.color = "var(--danger-text)";
        feedback.style.display = "block";
      } finally {
        btn.disabled = false;
        btn.textContent = "+ Register";
      }
    });
  }

  // Setup modal close handler
  const closeBtn = document.getElementById("close-onboarding-btn");
  if (closeBtn) {
    closeBtn.addEventListener("click", closeOnboardingModal);
  }
}

