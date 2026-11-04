import type { components } from "./types";

export type ApiErrorPayload = { error?: { code?: string; message?: string; details?: unknown } };

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;

  constructor(status: number, payload: ApiErrorPayload) {
    super(payload.error?.message ?? "Request failed");
    this.name = "ApiError";
    this.status = status;
    this.code = payload.error?.code ?? "INTERNAL_ERROR";
    this.details = payload.error?.details ?? {};
  }
}

const baseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const token = process.env.NEXT_PUBLIC_API_TOKEN ?? "verdict-demo-token";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, { ...init, headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...init?.headers } });
  const payload = (await response.json().catch(() => ({}))) as T & ApiErrorPayload;
  if (!response.ok) throw new ApiError(response.status, payload);
  return payload as T;
}

export type DisputeFilters = { status?: string; decision?: string; search?: string; sort?: "deadline" | "amount" | "created_at"; order?: "asc" | "desc"; page?: number; page_size?: number };
type Health = components["schemas"]["Health"];
type SimulationResponse = components["schemas"]["SimulationResponse"];
type DisputeListResponse = components["schemas"]["DisputeListResponse"];
type ApprovalItem = components["schemas"]["ApprovalItem"];
type SettingsResponse = components["schemas"]["SettingsSchema-Output"];

export const api = {
  getHealth: () => request<Health>("/health"),
  getDisputes: (filters: DisputeFilters = {}) => request<DisputeListResponse>(`/disputes?${new URLSearchParams(Object.entries(filters).filter((entry): entry is [string, string] => entry[1] !== undefined).map(([key, value]) => [key, String(value)]))}`),
  getDispute: (id: string) => request<Record<string, unknown>>(`/disputes/${encodeURIComponent(id)}`),
  getApprovals: () => request<ApprovalItem[]>("/approvals?status=PENDING"),
  approve: (id: string, note?: string) => request<Record<string, unknown>>(`/disputes/${encodeURIComponent(id)}/approve`, { method: "POST", body: JSON.stringify({ note }) }),
  reject: (id: string, note?: string) => request<Record<string, unknown>>(`/disputes/${encodeURIComponent(id)}/reject`, { method: "POST", body: JSON.stringify({ note }) }),
  runSimulation: (caseName: "A" | "B" | "C") => request<SimulationResponse>(`/sim/dispute?case=${caseName}`, { method: "POST" }),
  resetDemo: () => request<{ status: string }>("/seed/reset", { method: "POST" }),
  getSettings: () => request<SettingsResponse>("/settings"),
  updateSettings: (settings: SettingsResponse) => request<SettingsResponse>("/settings", { method: "PUT", body: JSON.stringify(settings) }),
  getMetrics: () => request<Record<string, unknown>>("/metrics"),
};
