"use client";

import { createWidgets, type AgWidgetDefinition } from "ag-studio-react";
import type { AgDefaultRegistry, AgWidgetsConfig } from "ag-studio";
import VerdictCardWidget from "./VerdictCardWidget";
import DeadlineRiskWidget from "./DeadlineRiskWidget";
import GuardrailActivityWidget from "./GuardrailActivityWidget";

type EmptyWidget = { dataMapping: Record<string, never>; format?: { title?: { enabled?: boolean; text?: string } } };

const makeDefinition = (id: string, label: string, comp: AgWidgetDefinition["comp"], description: string): AgWidgetDefinition => ({
  id,
  label,
  comp,
  form: (params) => params.createDefaults({ dataMappingItems: [] }),
  defaultSize: { width: 360, height: 240 },
  minSize: { width: 240, height: 160 },
  ai: { description, usage: "Read-only analysis widget. It cannot issue payment actions." },
});

const definitions = [
    makeDefinition("verdict-card", "Verdict Card", VerdictCardWidget, "Shows the latest dispute decision, win likelihood, confidence, rationale, and guardrail rule."),
    makeDefinition("deadline-risk", "Deadline Risk", DeadlineRiskWidget, "Ranks open disputes by time remaining and highlights urgent deadlines."),
    makeDefinition("guardrail-activity", "Guardrail Activity", GuardrailActivityWidget, "Shows which code-enforced guardrails prevented risky automatic actions."),
];

export const customWidgets = (defaults: AgWidgetsConfig<AgDefaultRegistry>) => createWidgets({
  additionalTypes: definitions as never,
  menu: [{ label: "Verdict", widgetIds: ["verdict-card", "deadline-risk", "guardrail-activity"] as never }, ...(defaults.menu ?? [])],
} as never) as never;

export type { EmptyWidget };
