import type { AgReportState } from "ag-studio";

/** Bump the version when the data model or default dashboard changes, so stale saved layouts are ignored. */
export const STATE_STORAGE_KEY = "verdict.studio.state.v2";

export const PAGES = [
  { id: "overview", label: "Overview" },
  { id: "risk", label: "Risk and guardrails" },
  { id: "explorer", label: "Case explorer" },
] as const;

type Aggregation = "count" | "sum" | "avg";

const title = (heading: string) => ({ title: { enabled: true, text: heading } });
const kpi = (id: string, aggregation: Aggregation, heading: string) => ({ type: "value", dataMapping: { value: [{ id, aggregation }] }, format: title(heading) });
const bar = (category: string, value: string, aggregation: Aggregation, heading: string) => ({ type: "bar-chart-grouped", dataMapping: { categoryKey: [{ id: category }], valueKey: [{ id: value, aggregation }] }, format: title(heading) });
const donut = (category: string, value: string, heading: string) => ({ type: "donut-chart", dataMapping: { categoryKey: [{ id: category }], valueKey: [{ id: value, aggregation: "count" }] }, format: title(heading) });
const listFilter = (id: string, heading: string) => ({ type: "list-filter", dataMapping: { value: [{ id }] }, format: title(heading) });
const place = (xTrack: number, yTrack: number, xSpan: number, ySpan: number) => ({ xTrack, yTrack, xSpan, ySpan });

/** The dashboard is 24 tracks wide. */
export const defaultState = {
  pages: [
    {
      id: "overview",
      widgets: {
        total: kpi("disputes.id", "count", "Disputes handled"),
        atRisk: kpi("amount_at_risk", "sum", "Amount at risk"),
        recovered: kpi("daily.modeled_revenue_recovered", "sum", "Modeled revenue recovered"),
        hours: kpi("daily.modeled_hours_saved", "sum", "Modeled hours saved"),
        status: donut("disputes.status", "disputes.id", "Dispute status"),
        decisions: bar("disputes.final_action", "disputes.id", "count", "Decisions"),
        verdict: { type: "verdict-card", dataMapping: {} },
        statusFilter: listFilter("disputes.status", "Filter by status"),
        decisionFilter: listFilter("disputes.final_action", "Filter by decision"),
      },
      widgetLayout: {
        total: place(0, 0, 6, 12),
        atRisk: place(6, 0, 6, 12),
        recovered: place(12, 0, 6, 12),
        hours: place(18, 0, 6, 12),
        status: place(0, 12, 8, 18),
        decisions: place(8, 12, 8, 18),
        verdict: place(16, 12, 8, 18),
        statusFilter: place(0, 30, 12, 14),
        decisionFilter: place(12, 30, 12, 14),
      },
    },
    {
      id: "risk",
      widgets: {
        deadline: { type: "deadline-risk", dataMapping: {} },
        guardrails: { type: "guardrail-activity", dataMapping: {} },
        windows: bar("deadline_bucket", "disputes.id", "count", "Open disputes by deadline window"),
        rules: bar("guardrails.rule", "guardrails.dispute_id", "count", "Guardrail interventions by rule"),
        evidenceByStatus: bar("disputes.status", "evidence.strength", "avg", "Average evidence strength by dispute status"),
        pipelineByDecision: bar("disputes.final_action", "audit.duration_ms", "avg", "Average pipeline time by decision (ms)"),
      },
      widgetLayout: {
        deadline: place(0, 0, 8, 20),
        guardrails: place(8, 0, 8, 20),
        windows: place(16, 0, 8, 20),
        rules: place(0, 20, 8, 18),
        evidenceByStatus: place(8, 20, 8, 18),
        pipelineByDecision: place(16, 20, 8, 18),
      },
    },
    {
      id: "explorer",
      widgets: {
        grid: {
          type: "grid",
          dataMapping: {
            cols: ["disputes.id", "disputes.customer_name", "disputes.amount_value", "disputes.win_likelihood", "disputes.confidence", "disputes.status", "disputes.final_action", "disputes.guardrail_rule", "deadline_bucket"].map((id) => ({ id })),
          },
          format: title("All disputes"),
        },
      },
      widgetLayout: { grid: place(0, 0, 24, 28) },
    },
  ],
  selectedPageId: "overview",
} as unknown as AgReportState;

/** Every field id referenced by the default dashboard (used by tests to catch typos). */
export function referencedFieldIds(): string[] {
  const ids: string[] = [];
  const visit = (value: unknown): void => {
    if (Array.isArray(value)) return value.forEach(visit);
    if (value && typeof value === "object") {
      const record = value as Record<string, unknown>;
      if (typeof record.id === "string" && ("aggregation" in record || Object.keys(record).length === 1)) ids.push(record.id);
      Object.values(record).forEach(visit);
    }
  };
  for (const page of (defaultState as unknown as { pages: { widgets: Record<string, { dataMapping?: unknown }> }[] }).pages) {
    for (const widget of Object.values(page.widgets)) visit(widget.dataMapping);
  }
  return ids;
}
