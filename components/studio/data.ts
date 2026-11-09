import type { AgExpressionFieldDefinition, AgFieldDefinition, AgRelationDefinition } from "ag-studio";
import { SOURCE_NAMES, STUDIO_SOURCE_IDS, expressions, fieldDefinitions, relationships, type StudioSourceId } from "./model";

export type AnalyticsRow = Record<string, string | number | boolean | null>;

export type StudioSource = { id: string; name: string; data: AnalyticsRow[]; fields: AgFieldDefinition[] };

export type StudioData = { sources: StudioSource[]; relationships: AgRelationDefinition[]; expressions: AgExpressionFieldDefinition[] };

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const token = process.env.NEXT_PUBLIC_API_TOKEN ?? "verdict-demo-token";

async function getRows(source: string): Promise<AnalyticsRow[]> {
  const response = await fetch(`${apiUrl}/analytics/${source}`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
  if (!response.ok) throw new Error(`Analytics source ${source} failed`);
  return response.json() as Promise<AnalyticsRow[]>;
}

/** Plain rows for the custom widgets. */
export async function fetchStudioSource(id: StudioSourceId): Promise<AnalyticsRow[]> {
  return getRows(id);
}

/** Everything AG Studio needs: sources with typed fields, the relationships between them, and calculated fields. */
export async function fetchStudioSources(): Promise<StudioData> {
  const rows = await Promise.all(STUDIO_SOURCE_IDS.map(getRows));
  return {
    sources: STUDIO_SOURCE_IDS.map((id, index) => ({ id, name: SOURCE_NAMES[id], data: rows[index], fields: fieldDefinitions[id] })),
    relationships,
    expressions,
  };
}
