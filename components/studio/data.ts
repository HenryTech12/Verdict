export type AnalyticsRow = Record<string, string | number | boolean | null>;

export type StudioSource = { id: string; data: AnalyticsRow[] };

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const token = process.env.NEXT_PUBLIC_API_TOKEN ?? "verdict-demo-token";

async function getRows(source: string): Promise<AnalyticsRow[]> {
  const response = await fetch(`${apiUrl}/analytics/${source}`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
  if (!response.ok) throw new Error(`Analytics source ${source} failed`);
  return response.json() as Promise<AnalyticsRow[]>;
}

export async function fetchStudioSources(): Promise<{ sources: StudioSource[] }> {
  const [disputes, evidence, audit, guardrails, daily] = await Promise.all(["disputes", "evidence", "audit", "guardrails", "daily"].map(getRows));
  return { sources: [{ id: "disputes", data: disputes }, { id: "evidence", data: evidence }, { id: "audit", data: audit }, { id: "guardrails", data: guardrails }, { id: "daily", data: daily }] };
}
