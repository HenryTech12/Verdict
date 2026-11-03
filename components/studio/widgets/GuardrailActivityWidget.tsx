"use client";

import type { AgWidgetParams } from "ag-studio";

export default function GuardrailActivityWidget(_params: AgWidgetParams) {
  return <div className="studio-custom-widget"><p className="eyebrow">GUARDRAIL ACTIVITY</p><h3>Risk controls in force</h3><div className="studio-bar"><span style={{ width: "72%" }} /></div><p className="studio-widget-copy">Guardrails prevent risky automatic actions. Amount thresholds, confidence, conflicts, and deadlines remain enforced in the backend.</p></div>;
}
