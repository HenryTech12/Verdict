import type { AgExpression, AgExpressionFieldDefinition, AgFieldDefinition, AgRelationDefinition } from "ag-studio";

/**
 * Data model for AG Studio: field definitions, relationships and calculated fields.
 * Field ids must match the keys returned by the backend /analytics/* endpoints.
 */
export const STUDIO_SOURCE_IDS = ["disputes", "evidence", "audit", "guardrails", "daily"] as const;
export type StudioSourceId = (typeof STUDIO_SOURCE_IDS)[number];

export const SOURCE_NAMES: Record<StudioSourceId, string> = {
  disputes: "Disputes",
  evidence: "Evidence checks",
  audit: "Audit trail",
  guardrails: "Guardrail events",
  daily: "Daily metrics",
};

export const OPEN_STATUSES = ["NEW", "ASSESSING", "AWAITING_APPROVAL"] as const;

type Row = Record<string, unknown>;

const toDate = (value: unknown): Date | null => {
  if (typeof value !== "string" || !value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
};

const text = (id: string, name: string): AgFieldDefinition => ({ id, name, format: "textFormat" });
const flag = (id: string, name: string): AgFieldDefinition => ({ id, name, format: "booleanFormat" });
const whole = (id: string, name: string): AgFieldDefinition => ({ id, name, format: "integerFormat" });
const money = (id: string, name: string): AgFieldDefinition => ({ id, name, format: "currencyFormat" });
const decimal = (id: string, name: string, format = "0.0"): AgFieldDefinition => ({ id, name, format: "decimalFormat", formatOptions: { format } });
const percent = (id: string, name: string): AgFieldDefinition => decimal(id, name, "0%"); // values are 0 to 1
// The accessor turns the API's ISO strings into Dates. The cast is needed because AgFieldDefinition's default
// format type is a string union, for which TypeScript cannot infer the Date return type.
const dateTime = (id: string, name: string): AgFieldDefinition => ({ id, name, format: "dateTimeFormat", accessor: ((row: Row) => toDate(row[id])) as unknown as AgFieldDefinition["accessor"] });

export const fieldDefinitions: Record<StudioSourceId, AgFieldDefinition[]> = {
  disputes: [
    text("id", "Dispute ID"),
    text("paypal_dispute_id", "PayPal dispute ID"),
    text("customer_name", "Customer"),
    money("amount_value", "Amount"),
    text("currency", "Currency"),
    text("reason", "Reason"),
    text("status", "Status"),
    text("decision", "Policy decision"),
    text("final_action", "Final action"),
    percent("win_likelihood", "Win likelihood"),
    percent("confidence", "Confidence"),
    percent("checklist_score", "Evidence checklist score"),
    text("rationale", "Agent rationale"),
    text("llm_error", "Model error"),
    flag("has_conflict", "Evidence conflict"),
    text("conflict_summary", "Conflict summary"),
    text("guardrail_rule", "Guardrail rule"),
    flag("simulated", "Simulated"),
    dateTime("created_at", "Created"),
    dateTime("deadline", "Response deadline"),
    decimal("hours_to_deadline", "Hours to deadline"),
    dateTime("resolved_at", "Resolved"),
    text("day", "Day"),
    text("week", "Week"),
  ],
  evidence: [
    text("dispute_id", "Dispute ID"),
    text("evidence_type", "Evidence type"),
    flag("present", "Present"),
    percent("strength", "Strength"),
    text("decision", "Decision"),
    text("status", "Status"),
    dateTime("created_at", "Created"),
  ],
  audit: [
    text("dispute_id", "Dispute ID"),
    text("step", "Pipeline step"),
    text("summary", "Summary"),
    flag("simulated", "Simulated"),
    whole("duration_ms", "Duration (ms)"),
    dateTime("ts", "Time"),
    text("day", "Day"),
  ],
  guardrails: [
    text("dispute_id", "Dispute ID"),
    text("rule", "Guardrail rule"),
    text("outcome", "Outcome"),
    flag("simulated", "Simulated"),
  ],
  daily: [
    text("day", "Day"),
    whole("disputes_opened", "Disputes opened"),
    whole("disputes_resolved", "Disputes resolved"),
    whole("refunds_issued", "Refunds issued"),
    whole("evidence_submitted", "Evidence submitted"),
    whole("escalated", "Escalated"),
    money("modeled_revenue_recovered", "Modeled revenue recovered"),
    decimal("modeled_hours_saved", "Modeled hours saved"),
  ],
};

const toDispute = (id: string, tableId: StudioSourceId): AgRelationDefinition => ({
  id,
  source: { tableId, fieldId: "dispute_id" },
  target: { tableId: "disputes", fieldId: "id" },
  type: "many-to-one",
});

/** Every evidence check, audit step and guardrail event belongs to exactly one dispute. */
export const relationships: AgRelationDefinition[] = [
  toDispute("evidence-dispute", "evidence"),
  toDispute("audit-dispute", "audit"),
  toDispute("guardrails-dispute", "guardrails"),
];

type Expression = Exclude<AgExpressionFieldDefinition["expression"], string>;

const isOpen: Expression = { operator: "in", inputs: [{ id: "disputes.status" }, ...OPEN_STATUSES.map((status) => ({ literal: status }))] };
const hoursLessThan = (hours: number): Expression => ({ operator: "lessThan", inputs: [{ id: "disputes.hours_to_deadline" }, { literal: hours }] });

export const expressions: AgExpressionFieldDefinition[] = [
  {
    id: "amount_at_risk",
    name: "Amount at risk",
    isMeasure: false,
    format: "currencyFormat",
    description: "Disputed amount of cases that are still open; zero once a case is closed.",
    expression: { operator: "if", inputs: [isOpen, { id: "disputes.amount_value" }, { literal: 0 }] },
  },
  {
    id: "deadline_bucket",
    name: "Deadline window",
    isMeasure: false,
    format: "textFormat",
    description: "How close an open dispute is to its response deadline.",
    expression: {
      operator: "if",
      inputs: [
        isOpen,
        { operator: "if", inputs: [hoursLessThan(24), { literal: "Under 24 hours" }, { operator: "if", inputs: [hoursLessThan(72), { literal: "1 to 3 days" }, { literal: "Over 3 days" }] }] },
        { literal: "Closed" },
      ],
    },
  },
];

/** Ids that widgets may reference: "source.field" or a calculated field id. */
export function knownFieldIds(): Set<string> {
  const ids = new Set<string>();
  for (const sourceId of STUDIO_SOURCE_IDS) for (const field of fieldDefinitions[sourceId]) ids.add(`${sourceId}.${field.id}`);
  for (const expression of expressions) ids.add(expression.id);
  return ids;
}

export type { AgExpression };
