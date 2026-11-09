"use client";
/* eslint-disable react-hooks/set-state-in-effect */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AgStudio, AgStudioProvider } from "ag-studio-react";
import { AgStudioAiModule, createAiHarness, type AgAiHarnessSetup, type AgReportState, type AgStudioMode } from "ag-studio";
import { fetchStudioSources, type StudioData } from "./data";
import { customWidgets } from "./widgets/registry";
import { groqStudioAdapter } from "./ai/adapter";
import { PAGES, STATE_STORAGE_KEY, defaultState } from "./state";

type Props = { openDispute: (id: string) => void };

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const apiToken = process.env.NEXT_PUBLIC_API_TOKEN ?? "verdict-demo-token";

/** The merchant's own edits to the dashboard, saved in this browser. Anything unreadable falls back to the default. */
function loadSavedState(): AgReportState | undefined {
  try {
    const raw = window.localStorage.getItem(STATE_STORAGE_KEY);
    if (!raw) return undefined;
    const parsed = JSON.parse(raw) as { pages?: unknown };
    return Array.isArray(parsed.pages) && parsed.pages.length > 0 ? (parsed as unknown as AgReportState) : undefined;
  } catch {
    return undefined;
  }
}

export default function VerdictStudio({ openDispute }: Props) {
  const studioRef = useRef<AgStudio>(null);
  const saveTimer = useRef<number | undefined>(undefined);
  const [data, setData] = useState<StudioData>();
  const [initialState, setInitialState] = useState<AgReportState>();
  const [error, setError] = useState<string>();
  const [aiEnabled, setAiEnabled] = useState(false);
  const [mode, setMode] = useState<AgStudioMode>("edit");
  const [page, setPage] = useState<string>("overview");

  // Restore the merchant's saved layout (client only, so it cannot cause a hydration mismatch).
  useEffect(() => {
    const saved = loadSavedState();
    setInitialState(saved ?? defaultState);
    const savedPage = (saved as unknown as { selectedPageId?: string } | undefined)?.selectedPageId;
    if (savedPage) setPage(savedPage);
  }, []);

  // Load analytics, refresh on live events, and ask the API whether the AI analyst is available.
  useEffect(() => {
    let disposed = false;
    let timer: number | undefined;
    let source: EventSource | undefined;
    const reload = () => {
      void fetchStudioSources()
        .then((next) => { if (!disposed) { setData(next); setError(undefined); } })
        .catch((reason: unknown) => { if (!disposed) setError(reason instanceof Error ? reason.message : "Analytics unavailable"); });
    };
    reload();
    void fetch(`${apiUrl}/health`)
      .then((response) => response.json() as Promise<{ llm_provider: string }>)
      .then((health) => { if (!disposed) setAiEnabled(health.llm_provider === "groq"); })
      .catch(() => undefined);
    try {
      source = new EventSource(`${apiUrl}/stream?token=${encodeURIComponent(apiToken)}`);
      const refresh = () => { if (timer) window.clearTimeout(timer); timer = window.setTimeout(reload, 500); };
      ["dispute_created", "dispute_updated", "audit_added", "metrics_updated"].forEach((name) => source?.addEventListener(name, refresh));
    } catch {
      setError("Live analytics stream unavailable");
    }
    return () => { disposed = true; if (timer) window.clearTimeout(timer); source?.close(); };
  }, []);

  const widgets = useMemo(() => customWidgets, []);
  const context = useMemo(() => ({ openDispute }), [openDispute]);
  const ai = useMemo<AgAiHarnessSetup | undefined>(
    () => aiEnabled
      ? ({ api }) => createAiHarness(api, {
          adapter: groqStudioAdapter,
          promptStarters: [
            { label: "Deadline risk", prompt: "Which disputes are closest to their deadline?" },
            { label: "Guardrails", prompt: "Show how many risky actions the guardrails blocked this month" },
            { label: "Weekly decisions", prompt: "Chart refunds vs fights by week" },
          ],
        })
      : undefined,
    [aiEnabled],
  );

  const selectPage = useCallback((id: string) => {
    const api = studioRef.current?.api;
    if (!api) return;
    api.setState({ ...api.getState(), selectedPageId: id });
    setPage(id);
  }, []);

  const toggleMode = useCallback(() => setMode((current) => (current === "edit" ? "view" : "edit")), []);

  const resetLayout = useCallback(() => {
    try { window.localStorage.removeItem(STATE_STORAGE_KEY); } catch { /* storage unavailable */ }
    studioRef.current?.api.setState(defaultState);
    setPage("overview");
  }, []);

  // Auto-save every layout change (debounced) and keep the page tabs in step with the dashboard.
  const onStateUpdated = useCallback((event: { state: AgReportState }) => {
    const selected = (event.state as unknown as { selectedPageId?: string }).selectedPageId;
    if (selected) setPage(selected);
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      try { window.localStorage.setItem(STATE_STORAGE_KEY, JSON.stringify(event.state)); } catch { /* storage full or unavailable */ }
    }, 600);
  }, []);

  useEffect(() => () => { if (saveTimer.current) window.clearTimeout(saveTimer.current); }, []);

  if (error) return <div className="studio-fallback"><p className="eyebrow">AG STUDIO</p><strong>{error}</strong><span>Start the FastAPI backend and refresh this dashboard.</span></div>;
  if (!data || !initialState) return <div className="studio-fallback"><p className="eyebrow">AG STUDIO</p><strong>Loading analytics…</strong></div>;

  return (
    <AgStudioProvider modules={[AgStudioAiModule]} licenseKey={process.env.NEXT_PUBLIC_AG_STUDIO_LICENSE_KEY}>
      <div className="studio-toolbar" role="toolbar" aria-label="Dashboard controls">
        <div className="studio-pages" role="tablist" aria-label="Dashboard pages">
          {PAGES.map((item) => <button key={item.id} type="button" role="tab" aria-selected={page === item.id} className="studio-action" onClick={() => selectPage(item.id)}>{item.label}</button>)}
        </div>
        <div className="studio-actions">
          <button type="button" className="studio-action" aria-pressed={mode === "edit"} onClick={toggleMode}>{mode === "edit" ? "Switch to view mode" : "Edit dashboard"}</button>
          <button type="button" className="studio-action" onClick={resetLayout}>Reset layout</button>
        </div>
      </div>
      <div className="studio-frame">
        <AgStudio ref={studioRef} data={data} widgets={widgets} initialState={initialState} mode={mode} ai={ai} context={context} onStateUpdated={onStateUpdated} />
      </div>
    </AgStudioProvider>
  );
}
