import { useCallback, useEffect, useState } from "react";
import { clearSession, getToken } from "./auth";

/** One place that knows how to talk to the API and how errors come back. */
export class ApiError extends Error {
  constructor(status, detail) {
    const message =
      (detail && (detail.message || detail.detail?.message || detail.detail)) ||
      `Request failed (${status})`;
    super(typeof message === "string" ? message : JSON.stringify(message));
    this.status = status;
    this.detail = detail?.detail ?? detail;
  }
}

async function request(path, { method = "GET", body } = {}) {
  const headers = {};
  if (body) headers["Content-Type"] = "application/json";
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(`/api${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (response.status === 401 && path !== "/auth/login") {
    clearSession();
    window.dispatchEvent(new Event("auth:logout"));
  }
  if (!response.ok) throw new ApiError(response.status, payload);
  return payload;
}

export const api = {
  get: (path) => request(path),
  post: (path, body) => request(path, { method: "POST", body }),
  patch: (path, body) => request(path, { method: "PATCH", body }),
  del: (path) => request(path, { method: "DELETE" }),
};

/** Fetch on mount and whenever a dependency changes, with a manual reload. */
export function useApi(path, deps = []) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    if (path === null) return;
    let live = true;
    setLoading(true);
    api
      .get(path)
      .then((result) => live && (setData(result), setError(null)))
      .catch((err) => live && setError(err))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);

  useEffect(() => load(), [load]);
  return { data, error, loading, reload: load };
}

// --- formatting -----------------------------------------------------------
// Indian digit grouping throughout: 12,34,567 not 1,234,567.

const inr0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const inr2 = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export const money = (value) => `₹${inr0.format(Math.round(value || 0))}`;
export const money2 = (value) => `₹${inr2.format(value || 0)}`;
export const num = (value) => inr0.format(value || 0);

/** Compact rupees for tiles and axes: 1.2 Cr, 4.5 L, 12.3 K. */
export function moneyShort(value) {
  const amount = Math.abs(value || 0);
  const sign = (value || 0) < 0 ? "-" : "";
  if (amount >= 1e7) return `${sign}₹${(amount / 1e7).toFixed(2)} Cr`;
  if (amount >= 1e5) return `${sign}₹${(amount / 1e5).toFixed(2)} L`;
  if (amount >= 1000) return `${sign}₹${(amount / 1000).toFixed(1)} K`;
  return `${sign}₹${inr0.format(Math.round(amount))}`;
}

export function date(value) {
  if (!value) return "—";
  return new Date(`${value}T00:00:00`).toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export function dateShort(value) {
  if (!value) return "—";
  return new Date(`${value}T00:00:00`).toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
  });
}

export const WEEKDAYS = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
];

export const todayIso = () => new Date().toISOString().slice(0, 10);

/** Cases + loose pieces, the way the trade says it. */
export function qtyLabel(cases, loose) {
  const bits = [];
  if (cases) bits.push(`${num(cases)} cs`);
  if (loose) bits.push(`${num(loose)} pc`);
  return bits.join(" + ") || "—";
}
