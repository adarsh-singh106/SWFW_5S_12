/**
 * Administrator Authentication, First-Run Setup, and Session Management.
 */

import {
  getOperatorToken,
  setOperatorToken,
  clearOperatorToken,
  isAuthenticated,
  setIsAuthenticated,
  getCsrfToken,
  setCsrfToken,
  getMustChangePassword,
  setMustChangePassword,
  getAuthMode,
  setAuthMode,
  incrementSelectionEpoch,
  abortAllActiveRequests,
  setSelectedNodeId
} from "./state.js";
import { boundedFetch, showAlert } from "./api.js";
import { fetchFleetStatus } from "./fleet.js";
import { activateDialog, deactivateDialog } from "./dialog-ownership.js";

let errorDismissTimer = null;

export function displayAuthError(msg) {
  const errBox = document.getElementById("auth-error");
  if (!errBox) return;
  if (errorDismissTimer) {
    clearTimeout(errorDismissTimer);
    errorDismissTimer = null;
  }
  if (!msg) {
    errBox.textContent = "";
    errBox.style.display = "none";
    return;
  }
  errBox.textContent = msg;
  errBox.style.display = "block";
  errorDismissTimer = setTimeout(() => {
    errBox.style.display = "none";
    errBox.textContent = "";
    errorDismissTimer = null;
  }, 5000);
}

export function clearAuthError() {
  const errBox = document.getElementById("auth-error");
  if (!errBox) return;
  if (errorDismissTimer) {
    clearTimeout(errorDismissTimer);
    errorDismissTimer = null;
  }
  errBox.style.display = "none";
  errBox.textContent = "";
}

export function switchAuthView(mode) {
  setAuthMode(mode);
  const setupView = document.getElementById("auth-setup-view");
  const loginView = document.getElementById("auth-login-view");
  const changePwView = document.getElementById("auth-change-password-view");
  const modalTitle = document.getElementById("auth-modal-title");
  const modalSubtitle = document.getElementById("auth-modal-subtitle");
  const errBox = document.getElementById("auth-error");
  const successBox = document.getElementById("auth-success");

  clearAuthError();
  if (successBox) successBox.style.display = "none";

  if (setupView) setupView.style.display = mode === "setup" ? "block" : "none";
  if (loginView) loginView.style.display = mode === "login" ? "block" : "none";
  if (changePwView) changePwView.style.display = mode === "change-password" ? "block" : "none";

  if (modalTitle) {
    if (mode === "setup") {
      modalTitle.textContent = "Administrator First-Run Setup";
    } else if (mode === "change-password") {
      modalTitle.textContent = "Change Administrator Password";
    } else {
      modalTitle.textContent = "Operator Authentication";
    }
  }

  if (modalSubtitle) {
    if (mode === "setup") {
      modalSubtitle.textContent = "Initialize Instance Security";
    } else if (mode === "change-password") {
      modalSubtitle.textContent = "Establish Permanent Credential";
    } else {
      modalSubtitle.textContent = "Fleet Operations Console Access";
    }
  }

  if (document.getElementById("auth-modal")?.style.display === "flex") {
    const targetId = mode === "setup" ? "setup-password"
      : mode === "change-password" ? "change-current-password" : "token-input";
    document.getElementById(targetId)?.focus();
  }
}

export function showAuthModal(errMsg = "", initialView = null) {
  const modal = document.getElementById("auth-modal");
  const errBox = document.getElementById("auth-error");
  if (!modal) return;

  if (initialView) {
    switchAuthView(initialView);
  } else if (getMustChangePassword()) {
    switchAuthView("change-password");
  }

  activateDialog(modal, { priority: true });
  modal.style.display = "flex";

  if (errBox) {
    if (errMsg) {
      displayAuthError(errMsg);
    } else {
      clearAuthError();
    }
  }

  const mode = getAuthMode();
  let focusTarget = null;
  if (mode === "setup") {
    focusTarget = document.getElementById("setup-password");
  } else if (mode === "change-password") {
    const curr = document.getElementById("change-current-password");
    focusTarget = curr && curr.value ? document.getElementById("change-new-password") : curr;
  } else {
    focusTarget = document.getElementById("token-input");
  }

  if (focusTarget && typeof focusTarget.focus === "function") {
    focusTarget.focus();
  }
}

export function hideAuthModal() {
  const modal = document.getElementById("auth-modal");
  if (!modal) return;
  modal.style.display = "none";
  deactivateDialog(modal);
}

export function updateAuthUI() {
  const logoutBtn = document.getElementById("logout-btn");
  const changePwNavBtn = document.getElementById("change-password-nav-btn");
  const isAuth = isAuthenticated();

  if (logoutBtn) {
    logoutBtn.style.display = isAuth ? "inline-flex" : "none";
  }
  if (changePwNavBtn) {
    changePwNavBtn.style.display = isAuth ? "inline-flex" : "none";
  }
}

export function initAuth({ skipInitialCheck = false } = {}) {
  const authModal = document.getElementById("auth-modal");
  const authForm = document.getElementById("auth-form");
  const setupForm = document.getElementById("setup-form");
  const changePwForm = document.getElementById("change-password-form");
  const tokenInput = document.getElementById("token-input");
  const toggleTokenBtn = document.getElementById("toggle-token-btn");
  const toggleSetupBtn = document.getElementById("toggle-setup-password-btn");
  const toggleChangeBtn = document.getElementById("toggle-change-password-btn");
  const changePwNavBtn = document.getElementById("change-password-nav-btn");
  const logoutBtn = document.getElementById("logout-btn");
  const changeSignoutBtn = document.getElementById("change-password-signout-btn");

  // Show/hide password controls
  if (toggleTokenBtn && tokenInput) {
    toggleTokenBtn.addEventListener("click", () => {
      tokenInput.type = tokenInput.type === "password" ? "text" : "password";
    });
  }

  if (toggleSetupBtn) {
    toggleSetupBtn.addEventListener("click", () => {
      const p1 = document.getElementById("setup-password");
      const p2 = document.getElementById("setup-confirm-password");
      if (p1 && p2) {
        const next = p1.type === "password" ? "text" : "password";
        p1.type = next;
        p2.type = next;
      }
    });
  }

  if (toggleChangeBtn) {
    toggleChangeBtn.addEventListener("click", () => {
      const p1 = document.getElementById("change-new-password");
      const p2 = document.getElementById("change-confirm-password");
      if (p1 && p2) {
        const next = p1.type === "password" ? "text" : "password";
        p1.type = next;
        p2.type = next;
      }
    });
  }

  const toggleSetupConfirmBtn = document.getElementById("toggle-setup-confirm-btn");
  if (toggleSetupConfirmBtn) {
    toggleSetupConfirmBtn.addEventListener("click", () => {
      const p2 = document.getElementById("setup-confirm-password");
      if (p2) {
        p2.type = p2.type === "password" ? "text" : "password";
      }
    });
  }

  const toggleChangeConfirmBtn = document.getElementById("toggle-change-confirm-btn");
  if (toggleChangeConfirmBtn) {
    toggleChangeConfirmBtn.addEventListener("click", () => {
      const p2 = document.getElementById("change-confirm-password");
      if (p2) {
        p2.type = p2.type === "password" ? "text" : "password";
      }
    });
  }

  // Clear auth error as soon as user types into any password field
  [
    tokenInput,
    document.getElementById("setup-password"),
    document.getElementById("setup-confirm-password"),
    document.getElementById("change-current-password"),
    document.getElementById("change-new-password"),
    document.getElementById("change-confirm-password")
  ].forEach(inp => {
    if (inp) {
      inp.addEventListener("input", clearAuthError);
    }
  });

  // Live inline validation: First-run setup
  const setupPw = document.getElementById("setup-password");
  const setupConfirm = document.getElementById("setup-confirm-password");
  const setupValMsg = document.getElementById("setup-validation-msg");
  function validateSetupInputs() {
    if (!setupPw || !setupConfirm || !setupValMsg) return;
    const v1 = setupPw.value || "";
    const v2 = setupConfirm.value || "";
    if (v1 && v1.length < 12) {
      setupValMsg.textContent = "Password must be at least 12 characters";
      setupValMsg.style.display = "block";
    } else if (v2 && v1 !== v2) {
      setupValMsg.textContent = "Passwords do not match";
      setupValMsg.style.display = "block";
    } else {
      setupValMsg.style.display = "none";
    }
  }
  if (setupPw && setupConfirm) {
    setupPw.addEventListener("input", validateSetupInputs);
    setupConfirm.addEventListener("input", validateSetupInputs);
  }

  // Live inline validation: Password change
  const changeNewPw = document.getElementById("change-new-password");
  const changeConfirm = document.getElementById("change-confirm-password");
  const changeValMsg = document.getElementById("change-validation-msg");
  function validateChangeInputs() {
    if (!changeNewPw || !changeConfirm || !changeValMsg) return;
    const v1 = changeNewPw.value || "";
    const v2 = changeConfirm.value || "";
    if (v1 && v1.length < 12) {
      changeValMsg.textContent = "Password must be at least 12 characters";
      changeValMsg.style.display = "block";
    } else if (v2 && v1 !== v2) {
      changeValMsg.textContent = "Passwords do not match";
      changeValMsg.style.display = "block";
    } else {
      changeValMsg.style.display = "none";
    }
  }
  if (changeNewPw && changeConfirm) {
    changeNewPw.addEventListener("input", validateChangeInputs);
    changeConfirm.addEventListener("input", validateChangeInputs);
  }

  // View 1: Handle First-Run Setup Form Submission
  if (setupForm) {
    setupForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const pw = (setupPw?.value || "").trim();
      const confirm = (setupConfirm?.value || "").trim();
      const errBox = document.getElementById("auth-error");
      const submitBtn = document.getElementById("setup-submit-btn");

      if (pw.length < 12) {
        displayAuthError("Password must be at least 12 characters long.");
        return;
      }
      if (pw !== confirm) {
        displayAuthError("Passwords do not match.");
        return;
      }

      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner"></span> Creating credential...';
      }

      try {
        const res = await boundedFetch("/api/auth/setup", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ password: pw, confirm_password: confirm })
        });
        const data = await res.json();
        if (res.ok) {
          setIsAuthenticated(true);
          setCsrfToken(data.csrf_token || null);
          setMustChangePassword(false);
          if (setupPw) setupPw.value = "";
          if (setupConfirm) setupConfirm.value = "";
          hideAuthModal();
          updateAuthUI();
          showAlert("Administrator setup completed successfully.", "success");
          fetchFleetStatus();
        } else {
          displayAuthError(data.error?.message || "Setup failed");
        }
      } catch (err) {
        displayAuthError("Failed to connect to Fleet Manager API: " + err.message);
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = "Complete Setup & Sign In";
        }
      }
    });
  }

  // View 2: Handle Login Form Submission
  if (authForm) {
    authForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = (tokenInput?.value || "").trim();
      if (!input) return;

      const submitBtn = document.getElementById("auth-submit-btn");
      const errBox = document.getElementById("auth-error");

      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner"></span> Signing in...';
      }

      try {
        const testRes = await boundedFetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ password: input })
        });

        if (testRes.status === 401) {
          displayAuthError("Invalid administrator password. Authentication failed.");
        } else if (testRes.status === 429) {
          displayAuthError("Too many failed attempts. Login is temporarily locked out.");
        } else if (testRes.ok) {
          const data = await testRes.json();
          setIsAuthenticated(true);
          setCsrfToken(data.csrf_token || null);
          setMustChangePassword(Boolean(data.must_change_password));

          if (data.must_change_password) {
            switchAuthView("change-password");
            const curr = document.getElementById("change-current-password");
            if (curr) curr.value = input;
            if (tokenInput) tokenInput.value = "";
            const newPw = document.getElementById("change-new-password");
            if (newPw && typeof newPw.focus === "function") newPw.focus();
          } else {
            hideAuthModal();
            updateAuthUI();
            if (tokenInput) tokenInput.value = "";
            showAlert("Administrator authenticated successfully.", "success");
            fetchFleetStatus();
          }
        } else {
          displayAuthError(`Server returned status ${testRes.status}`);
        }
      } catch (err) {
        displayAuthError("Failed to connect to Fleet Manager API: " + err.message);
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = "Sign In";
        }
      }
    });
  }

  // View 3: Handle Password Change Form Submission
  if (changePwForm) {
    changePwForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const curr = (document.getElementById("change-current-password")?.value || "").trim();
      const newPw = (document.getElementById("change-new-password")?.value || "").trim();
      const confirm = (document.getElementById("change-confirm-password")?.value || "").trim();
      const errBox = document.getElementById("auth-error");
      const submitBtn = document.getElementById("change-password-submit-btn");

      if (newPw.length < 12) {
        displayAuthError("New password must be at least 12 characters long.");
        return;
      }
      if (newPw !== confirm) {
        displayAuthError("New passwords do not match.");
        return;
      }
      if (newPw === "CHANGEME") {
        displayAuthError("Cannot use placeholder password 'CHANGEME'.");
        return;
      }

      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner"></span> Updating password...';
      }

      try {
        const headers = { "Content-Type": "application/json" };
        const csrf = getCsrfToken();
        if (csrf) headers["X-CSRF-Token"] = csrf;

        const res = await boundedFetch("/api/auth/change-password", {
          method: "POST",
          headers,
          body: JSON.stringify({
            current_password: curr,
            new_password: newPw,
            confirm_password: confirm
          })
        });
        const data = await res.json();
        if (res.ok) {
          setMustChangePassword(false);
          setCsrfToken(data.csrf_token || null);
          const currInput = document.getElementById("change-current-password");
          const newPwInput = document.getElementById("change-new-password");
          const confirmInput = document.getElementById("change-confirm-password");
          if (currInput) currInput.value = "";
          if (newPwInput) newPwInput.value = "";
          if (confirmInput) confirmInput.value = "";
          hideAuthModal();
          updateAuthUI();
          showAlert("Administrator password updated successfully.", "success");
          fetchFleetStatus();
        } else {
          if (res.status === 401) {
            const sessionRes = await boundedFetch("/api/auth/session");
            if (sessionRes.ok && !(await sessionRes.json()).authenticated) {
              clearOperatorToken();
              updateAuthUI();
              showAuthModal("Session expired. Please sign in again.", "login");
              return;
            }
          }
          displayAuthError(data.error?.message || "Password update failed");
        }
      } catch (err) {
        displayAuthError("Failed to update password: " + err.message);
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = "Save New Password & Continue";
        }
      }
    });
  }

  // Change Password Nav Button
  if (changePwNavBtn) {
    changePwNavBtn.addEventListener("click", () => {
      switchAuthView("change-password");
      showAuthModal();
    });
  }

  // Logout / Terminate Session
  for (const signoutButton of [logoutBtn, changeSignoutBtn]) {
    if (!signoutButton) continue;
    signoutButton.addEventListener("click", async () => {
      try {
        const headers = {};
        const csrf = getCsrfToken();
        if (csrf) headers["X-CSRF-Token"] = csrf;
        const response = await boundedFetch("/api/auth/logout", { method: "POST", headers });
        if (!response.ok) {
          showAlert("Logout failed. Please retry.", "danger");
          return;
        }
      } catch {
        showAlert("Logout failed. Please retry.", "danger");
        return;
      }

      clearOperatorToken();
      setIsAuthenticated(false);
      setMustChangePassword(false);
      incrementSelectionEpoch();
      abortAllActiveRequests();
      updateAuthUI();
      setSelectedNodeId(null);

      const opsActive = document.getElementById("ops-active-panel");
      const opsEmpty = document.getElementById("ops-empty-state");
      if (opsActive) opsActive.style.display = "none";
      if (opsEmpty) opsEmpty.style.display = "block";

      switchAuthView("login");
      showAuthModal("Session terminated. Please sign in to resume.");
    });
  }

  // Accessible Modal Keyboard Trap & Escape Handling
  if (authModal) {
    authModal.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && isAuthenticated() && !getMustChangePassword()) {
        hideAuthModal();
        return;
      }
      if (event.key !== "Tab") return;

      const focusable = Array.from(
        authModal.querySelectorAll("input, button, select, textarea, [tabindex]:not([tabindex='-1'])")
      ).filter(el => !el.disabled && el.offsetParent !== null);
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

  // Check initial session & setup state if not explicitly skipped
  if (!skipInitialCheck) {
    checkInitialSessionState();
  }
}

async function checkInitialSessionState() {
  try {
    const sessionRes = await boundedFetch("/api/auth/session");
    if (sessionRes.ok) {
      const sessData = await sessionRes.json();
      if (sessData.authenticated) {
        setIsAuthenticated(true);
        setOperatorToken("authenticated");
        setCsrfToken(sessData.csrf_token || null);
        setMustChangePassword(Boolean(sessData.must_change_password));
        updateAuthUI();

        if (sessData.must_change_password) {
          switchAuthView("change-password");
          showAuthModal();
        } else {
          hideAuthModal();
          fetchFleetStatus();
        }
        return;
      }
    }

    const statusRes = await boundedFetch("/api/auth/status");
    if (statusRes.ok) {
      const statusData = await statusRes.json();
      if (statusData.setup_required) {
        switchAuthView("setup");
      } else {
        switchAuthView("login");
      }
    } else {
      switchAuthView("login");
    }
  } catch {
    switchAuthView("login");
  }
}
