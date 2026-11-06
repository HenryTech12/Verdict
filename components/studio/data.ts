export type AnalyticsRow = Record<string, string | number | boolean | null>;

export type StudioSource = { id: string; data: AnalyticsRow[] };

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const token = process.env.NEXT_PUBLIC_API_TOKEN ?? "verdict-demo-token";

async function getRows(source: string): Promise<AnalyticsRow[]> {
  const response = await fetch(`${apiUrl}/analytics/${source}`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
  if (!response.ok) throw new Error(`Analytics source ${source} failed`);
  return response.json() as Promise<AnalyticsRow[]>;
}

export async function fetchStudioSource(id: "disputes" | "evidence" | "audit" | "guardrails" | "daily"): Promise<AnalyticsRow[]> {
  return getRows(id);
}

export async function fetchStudioSources(): Promise<{ sources: StudioSource[] }> {
  const ids = ["disputes", "evidence", "audit", "guardrails", "daily"] as const;
  const rows = await Promise.all(ids.map(getRows));
  return { sources: ids.map((id, index) => ({ id, data: rows[index] })) };
}
