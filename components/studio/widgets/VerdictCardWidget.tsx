"use client";

import type { AgWidgetParams } from "ag-studio";
import { ArrowUpRight, Scale } from "lucide-react";
import { useStudioRows, asNumber, asDate } from "./useStudioRows";
import { pretty } from "@/lib/format";

type VerdictContext = { openDispute?: (id: string) => void };
type Row = { id?: string; customer_name?: string; amount_value?: number; currency?: string; status?: string; decision?: string; final_action?: string; win_likelihood?: number; confidence?: number; rationale?: string; created_at?: string; guardrail_rule?: string };

export default function VerdictCardWidget(params: AgWidgetParams) {
  const context = params.context as VerdictContext;
  const title = (params as unknown as { format?: { style?: { heading?: string } } }).format?.style?.heading || "Decision intelligence";
  const { rows, loading, error } = useStudioRows("disputes");
  const latest = (rows as Row[]).filter((row) => row.decision).sort((a, b) => asDate(b.created_at) - asDate(a.created_at))[0];
  return <div className="studio-custom-widget">
    <div className="studio-widget-heading"><div><p className="eyebrow">LATEST VERDICT</p><h3>{title}</h3></div><span className="studio-widget-icon"><Scale size={17}/></span></div>
    {loading ? <p className="studio-widget-empty">Loading latest assessment…</p> : error ? <p className="studio-widget-error">{error}</p> : latest ? <>
      <div className="studio-verdict-meta"><span className={`studio-decision ${String(latest.decision).toLowerCase()}`}>{pretty(latest.final_action || latest.decision)}</span><span>{latest.id}</span></div>
      <div className="studio-verdict-metrics"><div><strong>{Math.round(asNumber(latest.win_likelihood) * 100)}%</strong><small>Win likelihood</small></div><div><strong>{Math.round(asNumber(latest.confidence) * 100)}%</strong><small>Confidence</small></div></div>
      {latest.rationale && <p className="studio-widget-copy">{latest.rationale}</p>}
      {latest.guardrail_rule && <p className="studio-widget-footnote">Guardrail: {pretty(latest.guardrail_rule)}</p>}
      <button className="studio-case-button" onClick={() => latest.id && context.openDispute?.(latest.id)}>Open dispute <ArrowUpRight size={14}/></button>
    </> : <p className="studio-widget-empty">No assessed disputes yet. Run a simulator case to create the first verdict.</p>}
  </div>;
}
