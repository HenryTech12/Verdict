"use client";

import { ShieldCheck } from "lucide-react";
import { useStudioRows } from "./useStudioRows";

type GuardrailRow = { rule?: string; outcome?: string; dispute_id?: string };

export default function GuardrailActivityWidget(params: import("ag-studio").AgWidgetParams) {
  const title = (params as unknown as { format?: { style?: { heading?: string } } }).format?.style?.heading || "Risk controls in force";
  const { rows, loading, error } = useStudioRows("guardrails");
  const items = rows as GuardrailRow[];
  const counts = items.reduce<Record<string, number>>((acc, item) => { const key = item.rule || "OTHER"; acc[key] = (acc[key] || 0) + 1; return acc; }, {});
  const top = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 4);
  const total = items.length;
  return <div className="studio-custom-widget">
    <div className="studio-widget-heading"><div><p className="eyebrow">GUARDRAIL ACTIVITY</p><h3>{title}</h3></div><span className="studio-widget-icon"><ShieldCheck size={17}/></span></div>
    <div className="studio-widget-kpi"><strong>{loading ? "—" : total}</strong><span>guardrail interventions recorded</span></div>
    {error ? <p className="studio-widget-error">{error}</p> : top.length ? <div className="studio-rule-list">{top.map(([rule, count]) => <div className="studio-rule" key={rule}><div><span>{rule.replaceAll("_", " ").toLowerCase()}</span><b>{count}</b></div><div className="studio-rule-track"><i style={{ width: `${Math.max(5, (count / Math.max(total, 1)) * 100)}%` }}/></div></div>)}</div> : <p className="studio-widget-empty">No guardrail interventions have been recorded yet.</p>}
    <p className="studio-widget-footnote">Counts are sourced from recorded decision guardrails, not estimates.</p>
  </div>;
}
