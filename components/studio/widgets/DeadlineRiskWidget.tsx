"use client";

import type { AgWidgetParams } from "ag-studio";

type VerdictContext = { openDispute?: (id: string) => void };

export default function DeadlineRiskWidget(params: AgWidgetParams) {
  const context = params.context as VerdictContext;
  return <div className="studio-custom-widget"><p className="eyebrow">DEADLINE RISK</p><h3>Cases needing attention</h3><p className="studio-widget-copy">Open disputes under 24 hours are highlighted in danger red. Click a case to open the existing detail drawer.</p><button className="case-button" onClick={() => context.openDispute?.("")}>Explore cases</button></div>;
}
