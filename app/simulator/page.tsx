"use client";

import { useState } from "react";
import Link from "next/link";
import { api, type CaseName } from "@/lib/api/client";
import { timed } from "@/lib/timing";

const cases: { id: CaseName; title: string; detail: string; result: string; bonus?: boolean }[] = [
  { id: "A", title: "Easy fight", detail: "$80 item-not-received claim. Delivered, address matches, delivery photo present.", result: "FIGHT" },
  { id: "B", title: "Conflict moment", detail: "$90 claim. Tracking says delivered, but to an address that does not match the order.", result: "REFUND (auto, under the $100 cap)" },
  { id: "C", title: "High value", detail: "$480 claim with strong evidence. Guardrail forces human approval despite a FIGHT recommendation.", result: "ESCALATE, then approve and submit" },
  { id: "D", title: "Not as described", detail: "$70 claim under the second reason code, with its own checklist and a packing photo.", result: "FIGHT", bonus: true },
  { id: "E", title: "Urgent deadline", detail: "$300 claim with 6 hours left. Needs approval and is flagged urgent.", result: "ESCALATE (URGENT)", bonus: true },
  { id: "F", title: "Expired deadline", detail: "Deadline already passed. The agent logs and notifies, and takes no action.", result: "EXPIRED, no action", bonus: true },
];

export default function SimulatorPage() {
  const [notice, setNotice] = useState("Simulated data only");
  const [busy, setBusy] = useState(false);
  const run = async (id: CaseName) => {
    setBusy(true); setNotice(`Running Case ${id}...`);
    try { const { value, ms } = await timed(() => api.runSimulation(id)); setNotice(`Case ${id} created ${value.dispute_id} in ${ms} ms`); } catch { setNotice("Simulation failed. Is the API running?"); } finally { setBusy(false); }
  };
  const runAll = async () => { for (const item of cases.filter((c) => !c.bonus)) await run(item.id); };
  const reset = async () => { setBusy(true); try { await api.resetDemo(); setNotice("Demo data reset and reseeded"); } finally { setBusy(false); } };
  return <main className="main"><p className="eyebrow">VERDICT / SIMULATOR</p><h1>Scenario lab</h1>
    <div className="sidebar-note"><strong>SIMULATED DATA</strong><span>Each case seeds an order, shipment and messages, then fires a signed PayPal-style webhook at this app&apos;s own /webhooks/paypal endpoint. Nothing is charged in mock mode. <Link href="/">Back to the dashboard</Link></span></div>
    <div className="sim-card-grid">{cases.map((item) => <article className="sim-card" key={item.id}><p className="eyebrow">CASE {item.id}{item.bonus ? " · BONUS" : ""}</p><h2>{item.title}</h2><p>{item.detail}</p><span className="badge">Expected: {item.result}</span><button className="case-button primary" disabled={busy} onClick={() => void run(item.id)}>Run Case {item.id}</button></article>)}</div>
    <div className="sim-footer"><button className="case-button" disabled={busy} onClick={() => void reset()}>Reset demo data</button><button className="case-button primary" disabled={busy} onClick={() => void runAll()}>Run A, B and C</button><span aria-live="polite">{notice}</span></div></main>;
}
