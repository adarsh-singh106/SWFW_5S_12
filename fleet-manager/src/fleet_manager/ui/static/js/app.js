/**
 * Application Entry Point (ES Module).
 * Coordinates initialization of modular UI platform.
 */

import { initAuth, showAuthModal, updateAuthUI } from "./auth.js";
import { initFleet, fetchFleetStatus } from "./fleet.js";
import { initOnboarding } from "./node-onboarding.js";
import { initOperations } from "./operations.js";
import { initHistory } from "./history.js";
import {
  getOperatorToken,
  clearOperatorToken,
  isAuthenticated,
  getMustChangePassword
} from "./state.js";

function scrubCredentialURL() {
  try {
    const url = new URL(window.location.href);
    if (url.searchParams.has("token")) {
      url.searchParams.delete("token");
      window.history.replaceState(null, "", url.pathname + url.search + url.hash);
      return true;
    }
  } catch {
    // Ignore URL parse errors
  }
  return false;
}

function initApp() {
  scrubCredentialURL();
  initAuth();
  initFleet();
  initOnboarding();
  initOperations();
  initHistory();

  // Periodic auto-refresh every 10 seconds if authenticated
  setInterval(() => {
    if ((isAuthenticated() || getOperatorToken()) && !getMustChangePassword()) {
      fetchFleetStatus();
    }
  }, 10000);

  window.addEventListener("popstate", scrubCredentialURL);
  window.addEventListener("pageshow", (event) => {
    scrubCredentialURL();
    if (event.persisted) {
      clearOperatorToken();
      showAuthModal();
      updateAuthUI();
    }
  });
  showAuthModal();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initApp);
} else {
  initApp();
}

export { initApp };
