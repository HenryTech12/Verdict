"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { LayoutDashboard, Moon, Play, RotateCcw, Settings, ShieldCheck, Sparkles, Sun } from "lucide-react";
import VerdictStudio from "@/components/studio/VerdictStudio";
import DisputeDrawer, { type DisputeDetail } from "@/components/disputes/DisputeDrawer";
import DisputeGrid from "@/components/grid/DisputeGrid";
import ImpactPanel from "@/components/grid/ImpactPanel";
import { api, type CaseName } from "@/lib/api/client";
import { useLiveDisputes } from "@/lib/useLiveDisputes";
import { timed } from "@/lib/timing";

const CASES: { id: CaseName; label: string; hint: string }[] = [
  { id: "A", label: "A", hint: "Easy fight: delivered, address matches" },
  { id: "B", label: "B", hint: "Conflict: delivered to a different address" },
  { id: "C", label: "C", hint: "High value: guardrail forces approval" },
  { id: "D", label: "D", hint: "Not as described (second reason code)" },
  { id: "E", label: "E", hint: "Urgent: 6 hours left, needs approval" },
  { id: "F", label: "F", hint: "Expired deadline: no action" },
];

export default function Home() {
  const { disputes, pending, metrics, health, connected, error, toast, dismissToast, refresh } = useLiveDisputes();
  const [selected, setSelected] = useState<DisputeDetail | null>(null);
  const [notice, setNotice] = useState("Ready for a simulated case");
  const [dark, setDark] = useState(false);
  const [running, setRunning] = useState(false);
  const router = useRouter();

  const openDrawer = useCallback(async (id: string) => { setSelected((await api.getDispute(id)) as unknown as DisputeDetail); }, []);
  const onChanged = useCallback(() => void refresh(), [refresh]);

  async function runCase(caseName: CaseName) {
    setRunning(true); setNotice(`Running simulated Case ${caseName}...`);
    try { const { value, ms } = await timed(() => api.runSimulation(caseName)); setNotice(`Case ${caseName} complete in ${ms} ms · ${value.dispute_id}`); await refresh(); }
    catch { setNotice("Simulation failed"); }
    finally { setRunning(false); }
  }

  const paypalMode = (health?.paypal_mode ?? "mock").toUpperCase(), llm = (health?.llm_provider ?? "mock").toUpperCase();
  return <div className={dark ? "theme-dark min-h-screen" : "min-h-screen"}>
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">V</div><div><strong>Verdict</strong><span>Know which disputes to fight.</span></div></div>
      <div className="mode-row"><span className={`mode-pill ${paypalMode === "MOCK" ? "amber" : "blue"}`}><span /> PAYPAL: {paypalMode}</span><span className={`mode-pill ${llm === "MOCK" ? "amber" : "blue"}`}><span /> LLM: {llm}</span></div>
      <nav>
        <button className="nav-item active"><LayoutDashboard size={17} /><span>Dashboard</span></button>
        <button className="nav-item" onClick={() => router.push("/approvals")}><ShieldCheck size={17} /><span>Approvals</span>{pending > 0 && <b>{pending}</b>}</button>
        <button className="nav-item" onClick={() => router.push("/simulator")}><Play size={17} /><span>Simulator</span></button>
        <button className="nav-item" onClick={() => router.push("/settings")}><Settings size={17} /><span>Settings</span></button>
      </nav>
      <div className="sidebar-note"><Sparkles size={16} /><div><strong>{paypalMode === "MOCK" ? "SIMULATED PAYPAL CALLS" : "PAYPAL SANDBOX"}</strong><span>{paypalMode === "MOCK" ? "Refunds and evidence submissions are labeled mocks. No real money moves." : "Real sandbox calls where supported; any mock fallback is labeled in the audit log."}</span></div></div>
      <div className="sidebar-bottom"><button className="icon-button" title="Toggle theme" onClick={() => setDark(!dark)}>{dark ? <Sun size={17} /> : <Moon size={17} />}</button><span>Demo merchant</span></div>
    </aside>
    <main className="main">
      <header className="topbar">
        <div><p className="eyebrow">DISPUTE OPERATIONS / OVERVIEW</p><h1>Command center</h1></div>
        <div className="top-actions"><span className={connected ? "live-badge on" : "live-badge"}><i />{connected ? "LIVE" : "RECONNECTING"}</span><button className="icon-button" title="Refresh" onClick={() => void refresh()}><RotateCcw size={17} /></button></div>
      </header>
      {error && <p className="api-error" role="alert">{error}</p>}
      <ImpactPanel metrics={metrics} pending={pending} />
      <section className="workspace">
        <div className="workspace-head">
          <div><p className="eyebrow">ALL DISPUTES · CLICK A ROW FOR THE AGENT&apos;S REASONING</p><h2>Cases</h2></div>
          <div className="sim-controls"><span className="sim-label">SIMULATOR</span>{CASES.map((item) => <button className="case-button" key={item.id} disabled={running} title={item.hint} onClick={() => void runCase(item.id)}><Play size={13} fill="currentColor" /> Case {item.label}</button>)}</div>
        </div>
        <DisputeGrid disputes={disputes} dark={dark} onChanged={onChanged} openDrawer={(id) => void openDrawer(id)} />
      </section>
      <section className="studio-section"><div className="studio-section-head"><div><p className="eyebrow">AG STUDIO ANALYTICS</p><h2>Explore the dispute system</h2></div><span>Three saved pages</span></div><VerdictStudio openDispute={(id) => void openDrawer(id)} /></section>
      <p className="status-line" aria-live="polite"><span className="status-pulse" /> {notice}</p>
    </main>
    {selected && <DisputeDrawer detail={selected} onClose={() => setSelected(null)} onUpdated={(detail) => setSelected(detail)} onAction={onChanged} />}
    {toast && <div className="toast" role="status"><span>{toast}</span><button onClick={dismissToast}>Dismiss</button></div>}
  </div>;
}
