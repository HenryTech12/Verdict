"use client";

import { useEffect, useMemo, useState } from "react";
import { AgGridReact, type CustomCellRendererProps } from "ag-grid-react";
import { AllCommunityModule, ModuleRegistry, colorSchemeVariable, themeQuartz, type ColDef, type RowClassParams } from "ag-grid-community";
import { ChevronDown, ChevronRight, Search } from "lucide-react";
import type { Dispute } from "@/lib/api/client";
import DetailRow from "@/components/grid/DetailRow";
import type { GridContext, GridRow } from "@/components/grid/types";
import { STATUSES, STATUS_LABEL, money, pretty, sortDisputes, timeLeft } from "@/lib/format";

ModuleRegistry.registerModules([AllCommunityModule]);

const theme = themeQuartz.withPart(colorSchemeVariable).withParams({ fontFamily: "inherit", accentColor: "#0070e0", headerFontSize: 12, fontSize: 14, wrapperBorderRadius: 8 });
const DETAIL_HEIGHT = 560, ROW_HEIGHT = 58;

function useNow(intervalMs = 30000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const id = window.setInterval(() => setNow(Date.now()), intervalMs); return () => window.clearInterval(id); }, [intervalMs]);
  return now;
}

function IdCell({ data, context }: CustomCellRendererProps<GridRow>) {
  const open = (context as GridContext).expanded.has(data!.id);
  return <span className="case-id-cell">{open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}<span className="case-id">{data!.id}</span>{data!.simulated && <span className="sim-tag">SIM</span>}</span>;
}

function DeadlineCell({ data }: CustomCellRendererProps<GridRow>) {
  const left = timeLeft(data!.deadline, useNow());
  const closed = ["EVIDENCE_SUBMITTED", "REFUNDED", "RESOLVED"].includes(data!.status);
  if (closed) return <span className="deadline closed">Closed</span>;
  return <span className={`deadline ${left.level}`} title={new Date(data!.deadline).toLocaleString()}>{left.label}{left.level === "urgent" && data!.status === "AWAITING_APPROVAL" ? " · URGENT" : ""}</span>;
}

function LikelihoodCell({ value }: CustomCellRendererProps<GridRow>) {
  if (value == null) return <span className="assumption">Pending</span>;
  const pct = Math.round(Number(value) * 100);
  return <span className="likelihood" aria-label={`Win likelihood ${pct}%`}><span className="bar"><i className={pct >= 60 ? "hi" : pct < 35 ? "lo" : "mid"} style={{ width: `${pct}%` }} /></span><b>{pct}%</b></span>;
}

function DecisionCell({ data }: CustomCellRendererProps<GridRow>) {
  const final = data!.decision ?? null, policy = data!.policy_decision ?? null;
  if (!final) return <span className="assumption">Pending</span>;
  const base = final.replace("_APPROVED", "");
  return <span className={`decision-badge ${base.toLowerCase()}`} title={data!.guardrail_rule ? `Guardrail ${pretty(data!.guardrail_rule)} changed ${policy} to ${final}` : undefined}>{policy && policy !== base && !final.endsWith("_APPROVED") ? `${pretty(policy)} → ${pretty(base)}` : pretty(final.endsWith("_APPROVED") ? `${base} (approved)` : base)}</span>;
}

function StatusCell({ value }: CustomCellRendererProps<GridRow>) {
  return <span className={`status-chip s-${String(value).toLowerCase()}`}><span />{STATUS_LABEL[String(value)] ?? pretty(String(value))}</span>;
}

const columns: ColDef<GridRow>[] = [
  { field: "id", headerName: "Dispute", flex: 1.15, minWidth: 200, cellRenderer: IdCell },
  { field: "customer_name", headerName: "Customer", flex: 1.2, minWidth: 142, cellRenderer: ({ data }: CustomCellRendererProps<GridRow>) => <span><strong>{data!.customer_name}</strong><small className="sub">{data!.paypal_dispute_id}</small></span> },
  { field: "amount", headerName: "Amount", flex: 0.72, minWidth: 92, type: "rightAligned", valueGetter: (p) => Number(p.data?.amount), valueFormatter: (p) => money(p.value, p.data?.currency) },
  { field: "reason", headerName: "Reason", flex: 1.05, minWidth: 128, valueFormatter: (p) => pretty(p.value) },
  { field: "deadline", headerName: "Deadline", flex: 0.95, minWidth: 126, // The value includes the status so the cell redraws (and shows "Closed") when a case is resolved.
    valueGetter: (p) => `${p.data?.deadline ?? ""}|${p.data?.status ?? ""}`, cellRenderer: DeadlineCell,
    comparator: (a: string, b: string) => new Date(a.split("|")[0]).getTime() - new Date(b.split("|")[0]).getTime() },
  { field: "win_likelihood", headerName: "Win likelihood", flex: 1.05, minWidth: 142, cellRenderer: LikelihoodCell, comparator: (a, b) => (a ?? -1) - (b ?? -1) },
  { field: "decision", headerName: "Decision", flex: 1.0, minWidth: 132,
    // Include policy decision, guardrail rule and status so the badge redraws when any of them changes.
    valueGetter: (p) => [p.data?.decision ?? "", p.data?.policy_decision ?? "", p.data?.guardrail_rule ?? "", p.data?.status ?? ""].join("|"),
    comparator: (a: string, b: string) => a.split("|")[0].localeCompare(b.split("|")[0]), cellRenderer: DecisionCell },
  { field: "status", headerName: "Status", flex: 1.0, minWidth: 132, cellRenderer: StatusCell },
];

type Props = { disputes: Dispute[]; dark: boolean; onChanged: () => void; openDrawer: (id: string) => void };

export default function DisputeGrid({ disputes, dark, onChanged, openDrawer }: Props) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState<string>("ALL");
  const [query, setQuery] = useState("");

  const counts = useMemo(() => disputes.reduce<Record<string, number>>((acc, row) => ({ ...acc, [row.status]: (acc[row.status] ?? 0) + 1 }), {}), [disputes]);
  const rows = useMemo<GridRow[]>(() => {
    const q = query.trim().toLowerCase();
    const visible = sortDisputes(disputes).filter((row) => (filter === "ALL" || row.status === filter) && (!q || [row.id, row.customer_name, row.paypal_dispute_id].some((value) => value.toLowerCase().includes(q))));
    return visible.flatMap<GridRow>((row) => expanded.has(row.id) ? [row, { ...row, id: `${row.id}::detail`, __detail: true, parent: row.id, sig: `${row.status}|${row.decision}|${row.win_likelihood}` }] : [row]);
  }, [disputes, expanded, filter, query]);

  const context = useMemo<GridContext>(() => ({ onChanged, openDrawer, expanded }), [onChanged, openDrawer, expanded]);
  const toggle = (id: string) => setExpanded((current) => { const next = new Set(current); if (!next.delete(id)) next.add(id); return next; });

  return <div className="grid-shell">
    <div className="grid-toolbar">
      <div className="filters" role="tablist" aria-label="Filter by status">
        {["ALL", ...STATUSES].map((status) => <button key={status} role="tab" aria-selected={filter === status} className={filter === status ? "chip active" : "chip"} onClick={() => setFilter(status)}>{status === "ALL" ? "All" : STATUS_LABEL[status]}<b>{status === "ALL" ? disputes.length : counts[status] ?? 0}</b></button>)}
      </div>
      <label className="search"><Search size={15} /><input aria-label="Search disputes" placeholder="Search ID or customer" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
    </div>
    <div className="grid-frame" data-ag-theme-mode={dark ? "dark" : "light"} style={{ height: 620, width: "100%", colorScheme: dark ? "dark" : "light" }}>
      <AgGridReact<GridRow>
        theme={theme}
        rowData={rows}
        columnDefs={columns}
        defaultColDef={{ sortable: true, resizable: true, enableCellChangeFlash: true, wrapHeaderText: true, autoHeaderHeight: true }}
        context={context}
        getRowId={(params) => params.data.id}
        isFullWidthRow={(params) => Boolean(params.rowNode.data?.__detail)}
        fullWidthCellRenderer={DetailRow}
        getRowHeight={(params) => (params.data?.__detail ? DETAIL_HEIGHT : ROW_HEIGHT)}
        getRowClass={(params: RowClassParams<GridRow>) => params.data?.urgent && params.data.status === "AWAITING_APPROVAL" ? "row-urgent" : undefined}
        onRowClicked={(event) => { if (event.data && !event.data.__detail) toggle(event.data.id); }}
        suppressCellFocus
        animateRows={false}
        overlayNoRowsTemplate="No disputes match. Run a simulated case to see Verdict think."
      />
    </div>
  </div>;
}
