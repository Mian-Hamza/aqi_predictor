const API_BASE =
  import.meta.env.VITE_API_BASE || "http://localhost:8000";

async function get(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    cache: "no-store",
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));

    throw new Error(
      body.detail ||
        `Request to ${path} failed (${res.status})`
    );
  }

  return res.json();
}

export const api = {
  current: () => get("/api/current"),

  trend: (hours = 24) =>
    get(`/api/trend?hours=${hours}`),

  forecast: () =>
    get("/api/forecast"),

  explain: (horizon) =>
    get(`/api/explain/${horizon}`),

  // Force FastAPI to clear its cache and fetch fresh data
  forceRefresh: () =>
    get("/api/refresh"),
};