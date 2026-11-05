"use client";

import type { AgWidgetParams } from "ag-studio";

type VerdictContext = { openDispute?: (id: string) => void };

export default function VerdictCardWidget(params: AgWidgetParams) {
  const context = params.context as VerdictContext;
  const open = () => context.openDispute?.("");
  return <div className="studio-custom-widget"><p className="eyebrow">LATEST VERDICT</p><h3>Decision intelligence</h3><p className="studio-widget-copy">Select a dispute from the Case Explorer to inspect its evidence, confidence, and guardrails.</p><button className="case-button" onClick={open}>Open case</button></div>;
}
