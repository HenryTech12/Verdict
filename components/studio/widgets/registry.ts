"use client";

import { createWidgets, type AgWidgetDefinition } from "ag-studio-react";
import type { AgDefaultRegistry, AgWidgetsConfig } from "ag-studio";
import VerdictCardWidget from "./VerdictCardWidget";
import DeadlineRiskWidget from "./DeadlineRiskWidget";
import GuardrailActivityWidget from "./GuardrailActivityWidget";

const makeDefinition = (id: string, label: string, comp: AgWidgetDefinition["comp"], description: string): AgWidgetDefinition => ({
  id,
  label,
  comp,
  form: (params) => {
    const form = params.createDefaults({ dataMappingItems: [] });
    form.items[0]?.items.push({
      type: "section",
      key: "verdictDisplaySettings",
      label: "Display settings",
      items: [{ type: "textfield", id: "format.style.heading", label: "Widget heading" }],
    });
    return form;
  },
  defaultState: { format: { style: { heading: label } } } as never,
  defaultSize: { width: 380, height: 300 },
  minSize: { width: 260, height: 200 },
  ai: { description, usage: "Read-only analytics widget. It can inspect dispute data but cannot approve, refund, or submit evidence." },
});

const definitions = [
  makeDefinition("verdict-card", "Latest Verdict", VerdictCardWidget, "Shows the most recent real dispute assessment, decision, win likelihood, confidence and guardrail."),
  makeDefinition("deadline-risk", "Deadline Risk", DeadlineRiskWidget, "Ranks real open disputes by time remaining and lets the user open the selected dispute."),
  makeDefinition("guardrail-activity", "Guardrail Activity", GuardrailActivityWidget, "Summarises recorded deterministic guardrail interventions by rule."),
];

export const customWidgets = (defaults: AgWidgetsConfig<AgDefaultRegistry>) => createWidgets({
  additionalTypes: definitions as never,
  menu: [{ label: "Verdict intelligence", widgetIds: ["verdict-card", "deadline-risk", "guardrail-activity"] as never }, ...(defaults.menu ?? [])],
} as never) as never;
