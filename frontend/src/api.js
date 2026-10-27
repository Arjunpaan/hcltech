// api.js - Every call from the dashboard to the FastAPI backend goes through here.

// Backend address. Change it in frontend/.env (VITE_API_URL) if needed.
export const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

// Read the error message FastAPI sends back ("detail") so the user sees why something failed.
async function handle(response) {
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body.detail) message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON - keep the status text */
    }
    throw new Error(message);
  }
  return response.json();
}

export const api = {
  get: (path) => fetch(API_URL + path).then(handle),
  post: (path, body) =>
    fetch(API_URL + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) }).then(handle),
  put: (path, body) =>
    fetch(API_URL + path, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) }).then(handle),
};

// Full link to a backend page (e.g. a check log) that opens in a new tab.
export const link = (path) => API_URL + path;
