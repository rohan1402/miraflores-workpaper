// Talking to the server. The browser computes nothing about the return: it asks, and renders.
import { createContext, useContext, useEffect, useState } from "react";

// Who is acting, the replay date (null = now), and a way to refetch after an act.
export const AppContext = createContext({ me: null, names: {}, asOf: null, setAsOf: () => {}, refresh: () => {} });
export const useApp = () => useContext(AppContext);

// Reads that can be replayed to a date (?as_of=YYYY-MM-DD). Everything else is always "now".
const REPLAYABLE = ["/api/return", "/api/areas/", "/api/lines/", "/api/documents", "/api/findings", "/api/history",
  "/api/filing", "/api/search"];

export function withAsOf(path, asOf) {
  if (!path || !asOf || !REPLAYABLE.some((p) => path.startsWith(p))) return path;
  return `${path}${path.includes("?") ? "&" : "?"}as_of=${asOf}`;
}

export async function getJSON(path) {
  const res = await fetch(path, { credentials: "same-origin" });
  if (!res.ok) throw await apiError(res);
  return res.json();
}

export async function postJSON(path, body) {
  const res = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(messageOf(data, res.status)), { status: res.status, data });
  return data;
}

async function apiError(res) {
  const data = await res.json().catch(() => ({}));
  return Object.assign(new Error(messageOf(data, res.status)), { status: res.status, data });
}

function messageOf(data, status) {
  if (data.refused) return data.refused.join(" ");
  if (data.conflict) return `Someone changed this first (event ${data.conflict.id}). Look again before acting.`;
  return data.detail || `Request failed (${status})`;
}

// Fetch `path` and refetch whenever `refreshKey` changes (a live event arrived) or the replay date moves.
export function useApi(path, refreshKey) {
  const { asOf } = useApp();
  const full = withAsOf(path, asOf);
  const [state, setState] = useState({ data: null, error: null, loading: true });
  useEffect(() => {
    if (!full) return undefined;
    let cancelled = false;
    setState((s) => ({ ...s, loading: true }));
    getJSON(full)
      .then((data) => !cancelled && setState({ data, error: null, loading: false }))
      .catch((error) => !cancelled && setState({ data: null, error, loading: false }));
    return () => {
      cancelled = true;
    };
  }, [full, refreshKey]);
  return state;
}
