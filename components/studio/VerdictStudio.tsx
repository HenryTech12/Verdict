"use client";

import { useEffect, useMemo, useState } from "react";
import { AgStudio, AgStudioProvider } from "ag-studio-react";
import { AgStudioAiModule, type AgReportState } from "ag-studio";
import { fetchStudioSources, type StudioSource } from "./data";
import { customWidgets } from "./widgets/registry";

type Props = { openDispute: (id: string) => void };

const initialState = {
  pages: [
    {
      id: "overview",
      widgets: {
        value: { type: "value", dataMapping: { value: [{ id: "disputes.id", aggregation: "count" }] } },
        status: { type: "donut-chart", dataMapping: { categoryKey: [{ id: "disputes.status" }], valueKey: [{ id: "disputes.id", aggregation: "count" }] } },
        verdict: { type: "verdict-card", dataMapping: {} },
      },
      widgetLayout: {
        value: { xTrack: 0, yTrack: 0, xSpan: 8, ySpan: 10 },
        status: { xTrack: 8, yTrack: 0, xSpan: 8, ySpan: 18 },
        verdict: { xTrack: 16, yTrack: 0, xSpan: 8, ySpan: 18 },
      },
    },
    {
      id: "risk",
      widgets: {
        deadline: { type: "deadline-risk", dataMapping: {} },
        guardrails: { type: "guardrail-activity", dataMapping: {} },
        scatter: { type: "scatter-chart", dataMapping: { groupByKey: [{ id: "disputes.id" }], categoryKey: [{ id: "disputes.amount_value" }], valueKey: [{ id: "disputes.win_likelihood" }] } },
      },
      widgetLayout: {
        deadline: { xTrack: 0, yTrack: 0, xSpan: 8, ySpan: 18 },
        guardrails: { xTrack: 8, yTrack: 0, xSpan: 8, ySpan: 18 },
        scatter: { xTrack: 16, yTrack: 0, xSpan: 8, ySpan: 18 },
      },
    },
    {
      id: "explorer",
      widgets: {
        grid: { type: "grid", dataMapping: { cols: [{ id: "disputes.id" }, { id: "disputes.customer_name" }, { id: "disputes.amount_value" }, { id: "disputes.status" }, { id: "disputes.decision" }] } },
      },
      widgetLayout: { grid: { xTrack: 0, yTrack: 0, xSpan: 24, ySpan: 30 } },
    },
  ],
  selectedPageId: "overview",
} as unknown as AgReportState;

export default function VerdictStudio({ openDispute }: Props) {
  const [data, setData] = useState<{ sources: StudioSource[] } | undefined>();
  const [error, setError] = useState<string>();
  useEffect(() => { void fetchStudioSources().then(setData).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Analytics unavailable")); }, []);
  const widgets = useMemo(() => customWidgets, []);
  if (error) return <div className="studio-fallback"><p className="eyebrow">AG STUDIO</p><strong>{error}</strong><span>Start the FastAPI backend and refresh this dashboard.</span></div>;
  return <AgStudioProvider modules={[AgStudioAiModule]} licenseKey={process.env.NEXT_PUBLIC_AG_STUDIO_LICENSE_KEY}><div className="studio-frame"><AgStudio data={data} widgets={widgets} initialState={initialState} mode="view" context={{ openDispute }} /></div></AgStudioProvider>;
}
