"use client";

import { useState } from "react";
import { api } from "@/lib/api/client";

const cases = [{ id: "A", title: "Easy fight", detail: "Delivered, matching address, proof, and messages.", result: "FIGHT" }, { id: "B", title: "Conflict moment", detail: "Tracking delivered to an address that does not match.", result: "REFUND" }, { id: "C", title: "High value", detail: "Strong evidence, but above the approval threshold.", result: "ESCALATE" }] as const;

export default function SimulatorPage() {
  const [notice, setNotice] = useState("Simulated data only");
  const run = async (id: "A" | "B" | "C") => { setNotice(`Running Case ${id}...`); try { const result = await api.runSimulation(id); setNotice(`Created ${result.dispute_id}`); } catch { setNotice("Simulation failed"); } };
  const runAll = async () => { for (const item of cases) { await run(item.id); await new Promise((resolve) => window.setTimeout(resolve, 2000)); } };
  const reset = async () => { await api.resetDemo(); setNotice("Demo data reset and reseeded"); };
  return <main className="main"><p className="eyebrow">VERDICT / SIMULATOR</p><h1>Scenario lab</h1><div className="sidebar-note"><strong>SIMULATED DATA</strong><span>Cases use generated orders and evidence. They never charge a customer in mock mode.</span></div><div className="sim-card-grid">{cases.map((item) => <article className="sim-card" key={item.id}><p className="eyebrow">CASE {item.id}</p><h2>{item.title}</h2><p>{item.detail}</p><span className="badge">Expected: {item.result}</span><button className="case-button primary" onClick={() => void run(item.id)}>Run Case {item.id}</button></article>)}</div><div className="sim-footer"><button className="case-button" onClick={() => void reset()}>Reset demo data</button><button className="case-button primary" onClick={() => void runAll()}>Run all three</button><span>{notice}</span></div></main>;
}
