const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

async function get(path) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request to ${path} failed (${res.status})`);
  }
  return res.json();
}

export const api = {
  current: () => get("/api/current"),
  trend: (hours = 24) => get(`/api/trend?hours=${hours}`),
  forecast: () => get("/api/forecast"),
  explain: (horizon) => get(`/api/explain/${horizon}`),
};