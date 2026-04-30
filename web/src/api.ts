/**
 * Typed fetch wrapper for the signal-trck FastAPI backend.
 *
 * Decision 14: one api.ts, not six. Decision 23: types come from
 * `openapi-typescript` against FastAPI's `/openapi.json` so we never
 * hand-mirror Pydantic shapes.
 *
 * Errors surface as `ApiError` with the backend's stable string `code`
 * (see §Error handling in the Phase B plan). Callers switch on `code`
 * rather than parsing English `detail` messages.
 */

import type { components, paths } from "./api-types";

// Convenience aliases — saves callers from the verbose `components["schemas"]`.
// FastAPI generates a single `Chart` schema (no Input/Output split because
// our model doesn't have computed fields).
export type Chart = components["schemas"]["Chart"];
export type ChartInput = components["schemas"]["Chart"];
export type ChartListItem = components["schemas"]["ChartListItemResponse"];
export type Pair = components["schemas"]["PairResponse"];
export type Candle = components["schemas"]["CandleResponse"];
export type IndicatorResponse = components["schemas"]["IndicatorResponse"];
export type SRCandidatesResponse =
  components["schemas"]["SRCandidatesResponse"];
export type AIRunResponse = components["schemas"]["AIRunResponse"];

/** Stable error code enum from the backend's exception handler table. */
export type ApiErrorCode =
  | "INVALID_PAIR_ID"
  | "PAIR_NOT_FOUND"
  | "CHART_NOT_FOUND"
  | "CHART_SLUG_CONFLICT"
  | "SCHEMA_MISMATCH"
  | "DB_BUSY"
  | "INTERNAL"
  | "UNKNOWN";

export class ApiError extends Error {
  readonly status: number;
  readonly code: ApiErrorCode;
  readonly detail: string;

  constructor(status: number, code: ApiErrorCode, detail: string) {
    super(`${code} (${status}): ${detail}`);
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

// Vite dev server proxies /api/* to the FastAPI backend on :8000.
// In prod (`signal-trck serve`) the FastAPI app serves both the SPA assets
// and the API on the same origin, so /api/* still resolves correctly.
const API_PREFIX = "/api";

async function call<T>(
  method: string,
  path: string,
  body?: unknown,
  init?: RequestInit,
): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...((init?.headers as Record<string, string>) ?? {}),
  };
  const fetchInit: RequestInit = {
    method,
    headers,
    ...init,
  };
  if (body !== undefined && !(body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    fetchInit.body = JSON.stringify(body);
  } else if (body instanceof FormData) {
    fetchInit.body = body;
  }
  const resp = await fetch(`${API_PREFIX}${path}`, fetchInit);
  if (!resp.ok) {
    let code: ApiErrorCode = "UNKNOWN";
    let detail = resp.statusText;
    try {
      const data = (await resp.json()) as { code?: string; detail?: string };
      if (typeof data.code === "string") code = data.code as ApiErrorCode;
      if (typeof data.detail === "string") detail = data.detail;
    } catch {
      // body wasn't JSON — keep statusText
    }
    throw new ApiError(resp.status, code, detail);
  }
  if (resp.status === 204) {
    return undefined as T;
  }
  return (await resp.json()) as T;
}

// --- Pairs ---

export const listPairs = (): Promise<Pair[]> => call("GET", "/pairs");
export const createPair = (pair_id: string): Promise<Pair> =>
  call("POST", "/pairs", { pair_id });
export const removePair = (pair_id: string): Promise<void> =>
  call("DELETE", `/pairs/${encodeURIComponent(pair_id)}`);

// --- Candles ---

export const getCandles = (
  pair_id: string,
  interval: "1h" | "1d" | "1w",
  window_days: number,
): Promise<Candle[]> =>
  call(
    "GET",
    `/pairs/${encodeURIComponent(pair_id)}/candles?interval=${interval}&window_days=${window_days}`,
  );

// --- Indicators ---

export interface IndicatorParams {
  period?: number;
  fast?: number;
  slow?: number;
  signal?: number;
  stddev?: number;
}

export const getIndicator = (
  pair_id: string,
  name: string,
  interval: "1h" | "1d" | "1w",
  params: IndicatorParams,
): Promise<IndicatorResponse> => {
  const qs = new URLSearchParams({ interval });
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined) qs.set(k, String(v));
  }
  return call(
    "GET",
    `/pairs/${encodeURIComponent(pair_id)}/indicators/${encodeURIComponent(name)}?${qs.toString()}`,
  );
};

// --- S/R candidates ---

export const getSRCandidates = (
  pair_id: string,
  interval: "1h" | "1d" | "1w",
  window_days: number,
  top_n = 50,
): Promise<SRCandidatesResponse> =>
  call(
    "GET",
    `/pairs/${encodeURIComponent(pair_id)}/sr-candidates?interval=${interval}&window_days=${window_days}&top_n=${top_n}`,
  );

// --- Refresh ---

export const refreshPair = (
  pair_id: string,
  interval: "1h" | "1d",
  days: number,
): Promise<components["schemas"]["RefreshResponse"]> =>
  call("POST", `/pairs/${encodeURIComponent(pair_id)}/refresh`, {
    interval,
    days,
  });

// --- Charts ---

export const listCharts = (pair_id?: string): Promise<ChartListItem[]> => {
  const qs = pair_id ? `?pair_id=${encodeURIComponent(pair_id)}` : "";
  return call("GET", `/charts${qs}`);
};

export const getChart = (slug: string): Promise<Chart> =>
  call("GET", `/charts/${encodeURIComponent(slug)}`);

export const createChart = (chart: ChartInput): Promise<Chart> =>
  call("POST", "/charts", chart);

export const updateChart = (slug: string, chart: ChartInput): Promise<Chart> =>
  call("PUT", `/charts/${encodeURIComponent(slug)}`, chart);

export const deleteChart = (slug: string): Promise<void> =>
  call("DELETE", `/charts/${encodeURIComponent(slug)}`);

export const exportChart = async (slug: string): Promise<Blob> => {
  const resp = await fetch(`${API_PREFIX}/charts/${encodeURIComponent(slug)}/export`);
  if (!resp.ok) {
    throw new ApiError(resp.status, "UNKNOWN", resp.statusText);
  }
  // Re-format with stable indent for diffability — matches `chart_io.py` on the
  // backend, which uses `indent=2`.
  const text = await resp.text();
  const formatted = JSON.stringify(JSON.parse(text), null, 2);
  return new Blob([formatted], { type: "application/json" });
};

export const importChart = async (file: File | Blob): Promise<Chart> => {
  const fd = new FormData();
  fd.append("file", file, "chart.json");
  return call("POST", "/charts/import", fd);
};

// --- AI runs ---

export const listAIRuns = (pair_id: string): Promise<AIRunResponse[]> =>
  call("GET", `/pairs/${encodeURIComponent(pair_id)}/ai_runs`);

// --- Health ---

export const healthz = (): Promise<paths["/healthz"]["get"]["responses"]["200"]["content"]["application/json"]> =>
  call("GET", "/healthz");
