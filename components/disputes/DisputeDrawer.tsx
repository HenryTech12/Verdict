"use client";

import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Check, Clipboard, Clock3, Download, X } from "lucide-react";
import { ApiError, api } from "@/lib/api/client";

type DecisionRecord = { policy_decision: string; rule_fired?: string | null; guardrail_rule: string | null; final_action: string };
export type DisputeDetail = {
  id: string; customer_name: string; amount: string; currency: string; status: string; deadline: string; simulated: boolean;
  decision?: string | DecisionRecord | null;
  assessment?: { evidence_items: { type: string; present: boolean; strength: number; note: string }[]; conflicts: string[]; checklist_score: number; win_likelihood: number; confidence: number; rationale: string; packet_draft: string } | null;
  order?: { ship_address: string; paypal_capture_id: string };
  shipment?: { delivery_address: string; tracking: string; status: string };
  audit: { id?: number; step: string; summary: string; input?: unknown; output?: unknown; simulated: boolean; fallback_reason?: string; ts: string }[];
};

type Props = { detail: DisputeDetail; onClose: () => void; onUpdated: (detail: DisputeDetail) => void; onAction: () => void };

function decisionRecord(value: DisputeDetail["decision"]): DecisionRecord | null {
  if (!value) return null;
  return typeof value === "string" ? { policy_decision: value, guardrail_rule: null, final_action: value } : value;
}

export default function DisputeDrawer({ detail, onClose, onUpdated, onAction }: Props) {
  const [confirm, setConfirm] = useState<"approve" | "reject" | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [copied, setCopied] = useState(false);
  const [expanded, setExpanded] = useState<number | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const record = decisionRecord(detail.decision);
  const amount = new Intl.NumberFormat("en-US", { style: "currency", currency: detail.currency || "USD" }).format(Number(detail.amount));
  const pending = detail.status === "AWAITING_APPROVAL";

  useEffect(() => {
    function onKey(event: KeyboardEvent) { if (event.key === "Escape") { setConfirm(null); onClose(); } if (event.key === "Tab" && dialogRef.current && !dialogRef.current.contains(event.target as Node)) { event.preventDefault(); dialogRef.current.focus(); } }
    document.addEventListener("keydown", onKey); dialogRef.current?.focus(); return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function copyPacket() {
    const packet = detail.assessment?.packet_draft ?? "";
    try { await navigator.clipboard.writeText(packet); } catch { const area = document.createElement("textarea"); area.value = packet; document.body.appendChild(area); area.select(); document.execCommand("copy"); area.remove(); }
    setCopied(true); window.setTimeout(() => setCopied(false), 1500);
  }

  async function confirmAction() {
    if (!confirm) return;
    setBusy(true); setNotice("");
    try { const updated = confirm === "approve" ? await api.approve(detail.id, note) : await api.reject(detail.id, note); onUpdated(updated as unknown as DisputeDetail); onAction(); setConfirm(null); setNote(""); }
    catch (error) { const known = error instanceof ApiError && ["ALREADY_PROCESSED", "INVALID_STATE", "GUARDRAIL_BLOCKED"].includes(error.code); setNotice(known && error instanceof ApiError ? `${error.code}: ${error.message}` : "Action failed. Refresh and try again."); }
    finally { setBusy(false); }
  }

  const evidenceItems = Array.isArray(detail.assessment?.evidence_items)
  ? detail.assessment.evidence_items
  : [];

  const auditEntries = Array.isArray(detail.audit)
  ? detail.audit
  : [];

  const matched = detail.order?.ship_address === detail.shipment?.delivery_address;
  return <div className="drawer-backdrop" onClick={onClose}><aside className="drawer" ref={dialogRef} tabIndex={-1} aria-label={`Dispute ${detail.id}`} onClick={(event) => event.stopPropagation()}>
    <button className="close-button" aria-label="Close dispute details" onClick={onClose}><X size={19} /></button>
    <div className="drawer-head"><p className="eyebrow">{detail.id} {detail.simulated && <span className="sim-tag">SIMULATED</span>}</p><h2>{detail.customer_name}</h2><div className="drawer-meta"><strong>{amount}</strong><span className="status-chip">{detail.status}</span><span><Clock3 size={14} /> {new Date(detail.deadline).toLocaleString()}</span></div></div>
    <div className="verdict-card"><p className="eyebrow">AGENT VERDICT</p><h3>{record?.policy_decision === "REFUND" && detail.assessment?.conflicts?.length ? "Agent chose not to fight" : record?.policy_decision ?? "Pending"}</h3><p>{detail.assessment?.rationale}</p><div className="meter-row"><span>Win likelihood</span><b>{Math.round((detail.assessment?.win_likelihood ?? 0) * 100)}%</b></div><div className="meter"><span style={{ width: `${(detail.assessment?.win_likelihood ?? 0) * 100}%` }} /></div><div className="confidence"><span>Confidence</span><b>{Math.round((detail.assessment?.confidence ?? 0) * 100)}%</b></div></div>
    {detail.assessment?.conflicts?.length ? <div className="conflict"><AlertTriangle size={17} /><div><strong>Conflict detected</strong><span>{detail.assessment.conflicts.join("; ")}</span></div></div> : null}
    <section className="drawer-section"><p className="eyebrow">GUARDRAIL · POLICY RULE {record?.rule_fired ?? "n/a"}</p><h3>{record?.guardrail_rule ?? "No guardrail triggered"}</h3><p className="studio-widget-copy">{record?.guardrail_rule === "AMOUNT_ABOVE_APPROVAL_THRESHOLD" ? `Amount ${amount} is above the approval threshold, so a human must approve.` : "The decision passed the configured guardrails."}</p></section>
    <section className="drawer-section"><div className="section-heading"><div><p className="eyebrow">EVIDENCE</p><h3>Checklist</h3></div><span className="score">{Math.round((detail.assessment?.checklist_score ?? 0) * 100)} / 100</span></div>{evidenceItems.map((item) => <div className="evidence-row" key={item.type}><span className={item.present ? "evidence-icon present" : "evidence-icon"}>{item.present ? <Check size={13} /> : <X size={13} />}</span><div><strong>{item.type.replaceAll("_", " ")}</strong><span>{item.note}</span></div><b>{item.present ? `${Math.round(item.strength * 100)}%` : "Missing"}</b></div>)}</section>
    <section className="drawer-section"><div className="address-compare"><div><span>Order address</span><strong>{detail.order?.ship_address ?? "Unknown"}</strong></div><div><span>Delivery address</span><strong>{detail.shipment?.delivery_address ?? "Unknown"}</strong></div></div><p className={matched ? "match-label" : "mismatch-label"}>{matched ? "✓ Address match" : "✕ Mismatch"}</p></section>
    <section className="drawer-section"><div className="packet-head"><div><p className="eyebrow">EVIDENCE PACKET</p><h3>Preview</h3></div><div className="drawer-actions"><button className="icon-button" onClick={() => void copyPacket()} title="Copy evidence packet"><Clipboard size={16} /></button><button className="icon-button" onClick={() => void api.downloadPacket(detail.id)} title="Download evidence packet"><Download size={16} /></button></div></div><pre className="packet-preview">{detail.assessment?.packet_draft || "No packet available"}</pre>{copied && <span className="copied" aria-live="polite">Copied</span>}</section>
    <section className="drawer-section"><p className="eyebrow">AUDIT TIMELINE</p>{auditEntries.map((entry, index) => <div className="audit-entry" key={`${entry.id ?? index}-${entry.step}`}><button onClick={() => setExpanded(expanded === index ? null : index)}><b>{entry.step}</b><span>{entry.summary}</span><time>{new Date(entry.ts).toLocaleTimeString()}</time></button>{entry.simulated && <span className="sim-tag">SIMULATED</span>}{entry.fallback_reason && <span className="sim-tag">fallback: {entry.fallback_reason}</span>}{expanded === index && <pre>{JSON.stringify({ input: entry.input, output: entry.output }, null, 2)}</pre>}</div>)}</section>
    {notice && <p className="error-notice" aria-live="polite">{notice}</p>}{pending && <div className="drawer-actions"><textarea aria-label="Approval note (optional)" placeholder="Optional note" value={note} onChange={(event) => setNote(event.target.value)} /><div><button className="case-button" disabled={busy} onClick={() => setConfirm("reject")}>Reject</button><button className="case-button primary" disabled={busy} onClick={() => setConfirm("approve")}>Approve</button></div></div>}
    {confirm && <div className="confirm-backdrop"><div className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-title" tabIndex={-1}><h2 id="confirm-title">Confirm {confirm}</h2><p>{confirm === "approve" ? `Submit evidence for ${amount}` : `Reject the recommendation for ${amount} with no action`}</p><div><button className="case-button" onClick={() => setConfirm(null)}>Cancel</button><button className="case-button primary" disabled={busy} onClick={() => void confirmAction()}>{busy ? "Working..." : "Confirm"}</button></div></div></div>}
  </aside></div>;
}