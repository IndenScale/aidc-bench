import type { DashboardPayload, TrialDetail } from "./types";

const RAW_API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.trim() || "";
const API_BASE = RAW_API_BASE.replace(/\/+$/, "");

export function getDataSourceMode(): "cloudflare-api" | "static-json" {
  return API_BASE ? "cloudflare-api" : "static-json";
}

async function fetchJson<T>(url: string): Promise<T> {
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status} for ${url}`);
  }
  return (await resp.json()) as T;
}

/**
 * Load the benchmark dashboard payload.
 * Uses Cloudflare Workers API when VITE_API_BASE is configured, with seamless
 * fallback to static /data/dashboard.json so local dev and static hosting work identically.
 */
export async function loadDashboardPayload(): Promise<DashboardPayload> {
  if (API_BASE) {
    try {
      return await fetchJson<DashboardPayload>(`${API_BASE}/v1/dashboard`);
    } catch (err) {
      console.warn(`[dataProvider] API fetch failed (${String(err)}); falling back to /data/dashboard.json`);
    }
  }
  return fetchJson<DashboardPayload>("/data/dashboard.json");
}

/**
 * Load per-agent trial artifact bundles (verifier outputs, submissions, logs, L3 layouts).
 * Supports Cloudflare R2/D1 API with automatic fallback to static /data/trials/<slug>.json.
 */
export async function loadTrialsBySlug(slug: string): Promise<Record<string, TrialDetail>> {
  const encoded = encodeURIComponent(slug);
  if (API_BASE) {
    try {
      return await fetchJson<Record<string, TrialDetail>>(`${API_BASE}/v1/trials/${encoded}`);
    } catch (err) {
      console.warn(`[dataProvider] Trial API fetch failed for ${slug} (${String(err)}); falling back to static JSON`);
    }
  }
  return fetchJson<Record<string, TrialDetail>>(`/data/trials/${encoded}.json`);
}
