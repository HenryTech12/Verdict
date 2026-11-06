"use client";
/* eslint-disable react-hooks/set-state-in-effect */

import { useCallback, useEffect, useState } from "react";
import type { CustomCellRendererProps } from "ag-grid-react";
import { AlertTriangle, Check, Download, ExternalLink, X } from "lucide-react";
import { ApiError, api } from "@/lib/api/client";
import { money, pretty } from "@/lib/format";
import type { GridRow, GridContext } from "@/components/grid/types";

type Detail = {
  id: string; amount: string; currency: string; status: string; urgent?: boolean; simulated: boolean;
  assessment?: { evidence_items: { type: string; present: boolean; strength: number; note: string }[]; conflicts: string[]; checklist_score: number; win_likelihood: number; confidence: number; rationale: string; llm_error?: string | null } | null;
  decision?: { policy_decision: string; rule_fired: string | null; guardrail_rule: string | null; final_action: string } | null;
  approval?: { requested_action: string; status: string; decided_by?: string | null; note?: string | null } | null;
  order?: { ship_address: string } | null; shipment?: { delivery_address: string; tracking: string; status: string } | null;
  audit: { id: number; step: string; summary: string; simulated: boolean; duration_ms: number; ts: string }[];
};

const GUARD_COPY: Record<string, string> = {
  AMOUNT_ABOVE_APPROVAL_THRESHOLD: "The amount is above your approval threshold, so a human must approve.",
  REFUND_ABOVE_AUTO_REFUND_CAP: "The refund is above your auto-refund cap, so a human must approve.",
  CONFLICTING_EVIDENCE: "The evidence conflicts, so the agent will not fight without you.",
  LOW_CONFIDENCE: "The agent's confidence is below your threshold.",
  MISSING_EVIDENCE: "Order or shipment records are missing for this transaction.",
  DEADLINE_EXPIRED: "The response deadline passed. No action was taken.",
  PIPELINE_ERROR: "Automated handling failed and the case was escalated.",
};

export default function DetailRow(props: CustomCellRendererProps<GridRow>) {
  const row = props.data as GridRow, ctx = props.context as GridContext;
  const [detail, setDetail] = useState<Detail | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const load = useCallback(async () => { try { setDetail((await api.getDispute(row.parent as string)) as unknown as Detail); } catch { setMessage("Could not load details."); } }, [row.parent]);
  useEffect(() => { void load(); }, [load, row.sig]);

  async function decide(kind: "approve" | "reject") {
    setBusy(true); setMessage("");
    try { await (kind === "approve" ? api.approve(row.parent as string, note) : api.reject(row.parent as string, note)); setNote(""); await load(); ctx.onChanged(); }
    catch (error) { setMessage(error instanceof ApiError ? `${error.code}: ${error.message}` : "Action failed. Refresh and try again."); }
    finally { setBusy(false); }
  }

  if (!detail) return <div className="detail-row"><span className="assumption">{message || "Loading reasoning…"}</span></div>;
  const a = detail.assessment, d = detail.decision, pendingApproval = detail.status === "AWAITING_APPROVAL" && detail.approval?.status === "PENDING";
  const rule = d?.guardrail_rule ?? null;
  return <div className="detail-row" onClick={(event) => event.stopPropagation()}>
    <section className="detail-col">
      <p className="eyebrow">AGENT VERDICT {detail.simulated && <span className="sim-tag">SIMULATED</span>}</p>
      <h3>{d?.policy_decision === "REFUND" && a?.conflicts.length ? "Agent chose not to fight" : pretty(d?.policy_decision)}{rule && <span className="arrow"> → {pretty(d?.final_action)}</span>}</h3>
      <p className="rationale">{a?.rationale ?? "Assessment pending."}</p>
      <div className="meter-line"><span>Win likelihood</span><b>{Math.round((a?.win_likelihood ?? 0) * 100)}%</b><span>Confidence</span><b>{Math.round((a?.confidence ?? 0) * 100)}%</b></div>
      <p className="rule-line"><b>Rule fired:</b> {pretty(d?.rule_fired)} · <b>Guardrail:</b> {rule ? pretty(rule) : "none triggered"}</p>
      {rule && <p className="guard-note">{GUARD_COPY[rule] ?? "A guardrail changed the action."}</p>}
      {a?.llm_error && <p className="guard-note danger">Model error logged: {a.llm_error}</p>}
      {a?.conflicts.length ? <div className="conflict"><AlertTriangle size={17} /><div><strong>Conflict detected</strong><span>{a.conflicts.join("; ")}</span></div></div> : null}
      {detail.urgent && <p className="urgent-flag">URGENT: under 24 hours left</p>}
      {pendingApproval && <div className="approve-box"><p><b>Requested action:</b> {pretty(detail.approval?.requested_action)} · {money(detail.amount, detail.currency)}</p><input aria-label="Decision note" placeholder="Optional note" value={note} onChange={(e) => setNote(e.target.value)} /><div className="drawer-actions"><button className="primary" disabled={busy} onClick={() => void decide("approve")}><Check size={15} /> Approve {pretty(detail.approval?.requested_action)}</button><button disabled={busy} onClick={() => void decide("reject")}><X size={15} /> Reject</button></div></div>}
      {!pendingApproval && detail.approval && <p className="rule-line"><b>Approval:</b> {pretty(detail.approval.status)}{detail.approval.note ? ` · “${detail.approval.note}”` : ""}</p>}
      {message && <p className="guard-note danger" role="alert">{message}</p>}
    </section>
    <section className="detail-col">
      <p className="eyebrow">EVIDENCE CHECKLIST · SCORE {Math.round((a?.checklist_score ?? 0) * 100)}%</p>
      <ul className="checklist">{(a?.evidence_items ?? []).map((item) => <li key={item.type} className={item.present ? "ok" : "missing"}><span>{item.present ? "✓" : "✗"}</span><div><strong>{pretty(item.type)}</strong><small>{item.note}</small></div><i style={{ width: `${Math.round(item.strength * 100)}%` }} /></li>)}</ul>
      {detail.shipment && <p className="rule-line"><b>Tracking:</b> {detail.shipment.tracking} ({detail.shipment.status})<br /><b>Order address:</b> {detail.order?.ship_address}<br /><b>Delivered to:</b> {detail.shipment.delivery_address}</p>}
      <div className="drawer-actions"><button onClick={() => void api.downloadPacket(detail.id)}><Download size={15} /> Evidence packet</button><button onClick={() => ctx.openDrawer(detail.id)}><ExternalLink size={15} /> Full view</button></div>
    </section>
    <section className="detail-col">
      <p className="eyebrow">AUDIT TIMELINE</p>
      <ol className="timeline">{detail.audit.map((entry) => <li key={entry.id}><b>{entry.step}</b><span>{entry.summary}{entry.simulated && " · SIM"}</span><small>{new Date(entry.ts).toLocaleTimeString()}{entry.duration_ms ? ` · ${entry.duration_ms}ms` : ""}</small></li>)}</ol>
    </section>
  </div>;
}
