import { state } from "../stores/appState.js";

const API_BASE = String(import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
let unauthorizedHandler = null;

export function setUnauthorizedHandler(handler) {
  unauthorizedHandler = handler;
}

export async function api(url, options = {}) {
  const headers = options.body instanceof FormData
    ? { ...(options.headers || {}) }
    : { "content-type": "application/json", ...(options.headers || {}) };

  const response = await fetch(`${API_BASE}${url}`, {
    ...options,
    credentials: "include",
    headers
  });

  if (response.ok) {
    return response.status === 204 ? null : response.json();
  }

  let message = `请求失败 (${response.status})`;
  let detail = null;
  try {
    const payload = await response.json();
    message = payload.errorDetail?.message || payload.error || message;
    detail = payload.errorDetail || null;
  } catch { /* response does not contain JSON */ }

  const error = new Error(message);
  error.detail = detail;
  error.status = response.status;
  if (response.status === 401 && !url.startsWith("/api/auth/") && !url.startsWith("/api/account/")) {
    state.currentUser = null;
    unauthorizedHandler?.();
  }
  throw error;
}
