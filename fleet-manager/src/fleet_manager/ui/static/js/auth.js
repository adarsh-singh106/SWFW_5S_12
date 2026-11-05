/**
 * Operator Authentication Modal & In-Memory Bearer Token Management.
 */

import {
  getOperatorToken,
  setOperatorToken,
  clearOperatorToken,
  incrementSelectionEpoch,
  abortAllActiveRequests,
  setSelectedNodeId,
  getModalReturnFocus,
  setModalReturnFocus
} from "./state.js";
import { boundedFetch, showAlert } from "./api.js";
import { fetchFleetStatus } from "./fleet.js";

export function showAuthModal(errMsg = "") {
  const modal = document.getElementById("auth-modal");
  const errBox = document.getElementById("auth-error");
  if (!modal) return;

  if (modal.style.display !== "flex") {
    setModalReturnFocus(document.activeElement);
  }
  modal.style.display = "flex";

  if (errBox) {
    if (errMsg) {
      errBox.textContent = errMsg;
      errBox.style.display = "block";
    } else {
      errBox.style.display = "none";
    }
  }

  const tokenInput = document.getElementById("token-input");
  if (tokenInput && typeof tokenInput.focus === "function") {
    tokenInput.focus();
  }
}

export function hideAuthModal() {
  const modal = document.getElementById("auth-modal");
  if (!modal) return;
  modal.style.display = "none";

  const returnTarget = getModalReturnFocus();
  if (returnTarget && typeof returnTarget.focus === "function") {
    returnTarget.focus();
  }
}

export function updateAuthUI() {
  const logoutBtn = document.getElementById("logout-btn");
  if (!logoutBtn) return;
  if (getOperatorToken()) {
    logoutBtn.style.display = "inline-flex";
  } else {
    logoutBtn.style.display = "none";
  }
}

export function initAuth() {
  const authForm = document.getElementById("auth-form");
  const tokenInput = document.getElementById("token-input");
  const toggleTokenBtn = document.getElementById("toggle-token-btn");
  const logoutBtn = document.getElementById("logout-btn");
  const authModal = document.getElementById("auth-modal");

  // Toggle token password visibility
  if (toggleTokenBtn && tokenInput) {
    toggleTokenBtn.addEventListener("click", () => {
      tokenInput.type = tokenInput.type === "password" ? "text" : "password";
    });
  }

  // Handle Auth Form Submission
  if (authForm) {
    authForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = (tokenInput.value || "").trim();
      if (!input) return;

      const submitBtn = document.getElementById("auth-submit-btn");
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner"></span> Verifying...';
      }

      try {
        const testRes = await boundedFetch("/api/nodes/status", {
          headers: { "Authorization": "Bearer " + input }
        });

        if (testRes.status === 401) {
          const errBox = document.getElementById("auth-error");
          if (errBox) {
            errBox.textContent = "Invalid operator bearer token. Authentication failed.";
            errBox.style.display = "block";
          }
        } else if (testRes.ok) {
          setOperatorToken(input);
          hideAuthModal();
          updateAuthUI();
          tokenInput.value = "";
          showAlert("Operator authenticated. Session active in memory.", "success");
          fetchFleetStatus();
        } else {
          const errBox = document.getElementById("auth-error");
          if (errBox) {
            errBox.textContent = `Server returned status ${testRes.status}`;
            errBox.style.display = "block";
          }
        }
      } catch (err) {
        const errBox = document.getElementById("auth-error");
        if (errBox) {
          errBox.textContent = "Failed to connect to Fleet Manager API: " + err.message;
          errBox.style.display = "block";
        }
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = "Authenticate Session";
        }
      }
    });
  }

  // Logout / Lock Session
  if (logoutBtn) {
    logoutBtn.addEventListener("click", () => {
      clearOperatorToken();
      incrementSelectionEpoch();
      abortAllActiveRequests();
      updateAuthUI();
      setSelectedNodeId(null);

      const opsActive = document.getElementById("ops-active-panel");
      const opsEmpty = document.getElementById("ops-empty-state");
      if (opsActive) opsActive.style.display = "none";
      if (opsEmpty) opsEmpty.style.display = "block";

      showAuthModal("Session locked. Token cleared from memory.");
    });
  }

  // Accessible Modal Keyboard Trap & Escape Handling
  if (authModal) {
    authModal.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && getOperatorToken()) {
        hideAuthModal();
        return;
      }
      if (event.key !== "Tab") return;

      const focusable = Array.from(authModal.querySelectorAll("input, button, select, textarea, [tabindex]:not([tabindex='-1'])"))
        .filter(el => !el.disabled && el.offsetParent !== null);
      if (focusable.length === 0) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
  }
}
