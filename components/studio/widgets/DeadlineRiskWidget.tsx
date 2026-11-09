"use client";

import type { AgWidgetParams } from "ag-studio";
import { AlertTriangle, Clock3 } from "lucide-react";
import { useStudioRows, asNumber, asDate } from "./useStudioRows";

type VerdictContext = { openDispute?: (id: string) => void };
type Row = { id?: string; customer_name?: string; amount_value?: number; currency?: string; status?: string; deadline?: string; hours_to_deadline?: number; simulated?: boolean };
const closed = new Set(["EVIDENCE_SUBMITTED", "REFUNDED", "RESOLVED", "EXPIRED"]);

export default function DeadlineRiskWidget(params: AgWidgetParams) {
  const context = params.context as VerdictContext;
  const title = (params as unknown as { format?: { style?: { heading?: string } } }).format?.style?.heading || "Cases needing attention";
  const { rows, loading, error } = useStudioRows("disputes");
  const cases = (rows as Row[]).filter((row) => !closed.has(String(row.status)) && asNumber(row.hours_to_deadline) <= 72)
    .sort((a, b) => asDate(a.deadline) - asDate(b.deadline)).slice(0, 5);
  return <div className="studio-custom-widget">
    <div className="studio-widget-heading"><div><p className="eyebrow">DEADLINE RISK</p><h3>{title}</h3></div><span className="studio-widget-icon"><Clock3 size={17}/></span></div>
    <div className="studio-widget-kpi"><strong>{loading ? "—" : cases.length}</strong><span>open disputes due within 72 hours</span></div>
    {error ? <p className="studio-widget-error">{error}</p> : cases.length ? <div className="studio-widget-list">{cases.map((row) => <button className="studio-case-row" key={row.id} onClick={() => row.id && context.openDispute?.(row.id)}><span><b>{row.id}</b><small>{row.customer_name ?? "Unknown customer"}</small></span><strong className={`studio-risk-time ${asNumber(row.hours_to_deadline) < 24 ? "urgent" : "soon"}`}>{asNumber(row.hours_to_deadline) < 0 ? "Expired" : `${asNumber(row.hours_to_deadline).toFixed(1)}h left`}</strong></button>)}</div> : <p className="studio-widget-empty"><AlertTriangle size={15}/> No open disputes are due within 72 hours.</p>}
  </div>;
}
