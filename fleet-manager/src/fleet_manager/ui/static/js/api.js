/**
 * Centralized API request handling with bounded timeouts, cookie credentials, and CSRF protection.
 */

import {
  getOperatorToken,
  clearOperatorToken,
  isAuthenticated,
  setIsAuthenticated,
  getCsrfToken,
  trackActiveRequest,
  removeActiveRequest
} from "./state.js";
import { showAuthModal, updateAuthUI } from "./auth.js";

/**
 * Bounded fetch wrapper ensuring requests cannot hang indefinitely.
 * Includes response consumption within the deadline.
 * Sends credentials (cookies) with same-origin requests.
 */
export async function boundedFetch(path, options = {}, timeoutMs = 20000) {
  const controller = new AbortController();
  trackActiveRequest(controller);
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const fetchOptions = {
      credentials: "same-origin",
      ...options,
      signal: controller.signal
    };
    const response = await fetch(path, fetchOptions);
    const body = await response.text();
    return {
      ok: response.ok,
      status: response.status,
      headers: response.headers,
      text: async () => body,
      json: async () => JSON.parse(body)
    };
  } catch (error) {
    if (controller.signal.aborted) {
      throw new Error("Request timed out or cancelled; outcome may be unknown. Do not replay operations.");
    }
    throw error;
  } finally {
    clearTimeout(timer);
    removeActiveRequest(controller);
  }
}

/**
 * Perform an authenticated API request using session cookies and CSRF tokens.
 */
export async function apiRequest(path, options = {}) {
  const token = getOperatorToken();
  if (!isAuthenticated() && !token) {
    showAuthModal();
    throw new Error("Authentication required");
  }

  const headers = { ...(options.headers || {}) };
  // Only attach Bearer token if an explicit non-placeholder manual token is provided (e.g. test harness)
  if (token && token !== "authenticated") {
    headers["Authorization"] = "Bearer " + token;
  }

  // Include CSRF protection on state-changing requests
  const method = (options.method || "GET").toUpperCase();
  if (["POST", "PUT", "DELETE", "PATCH"].includes(method)) {
    const csrfToken = getCsrfToken();
    if (csrfToken) {
      headers["X-CSRF-Token"] = csrfToken;
    }
  }

  if (options.body && typeof options.body === "string" && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  const response = await boundedFetch(path, { ...options, headers });
  if (response.status === 401) {
    clearOperatorToken();
    setIsAuthenticated(false);
    updateAuthUI();
    showAuthModal("Session unauthorized or token expired. Please re-authenticate.", "login");
    throw new Error("Unauthorized");
  }
  return response;
}

/**
 * Display a global alert banner.
 */
export function showAlert(msg, type = "info", durationMs = 6000) {
  const alertBox = document.getElementById("global-alert");
  if (!alertBox) return;
  alertBox.className = `alert alert-${type}`;
  alertBox.textContent = msg;
  alertBox.style.display = "flex";
  if (durationMs > 0) {
    setTimeout(() => {
      if (alertBox.textContent === msg) {
        alertBox.style.display = "none";
      }
    }, durationMs);
  }
}
