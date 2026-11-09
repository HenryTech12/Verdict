import { describe, expect, it } from "vitest";
import { STUDIO_SOURCE_IDS, expressions, fieldDefinitions, knownFieldIds, relationships } from "./model";
import { PAGES, defaultState, referencedFieldIds } from "./state";

type Placement = { xTrack: number; yTrack: number; xSpan: number; ySpan: number };
type Page = { id: string; widgets: Record<string, unknown>; widgetLayout: Record<string, Placement> };
const pages = (defaultState as unknown as { pages: Page[] }).pages;

describe("AG Studio data model", () => {
  it("has unique field ids within every source", () => {
    for (const source of STUDIO_SOURCE_IDS) {
      const ids = fieldDefinitions[source].map((field) => field.id);
      expect(new Set(ids).size).toBe(ids.length);
    }
  });

  it("relates evidence, audit and guardrail rows to a dispute by id", () => {
    const known = knownFieldIds();
    expect(relationships.map((relation) => relation.id).sort()).toEqual(["audit-dispute", "evidence-dispute", "guardrails-dispute"]);
    for (const relation of relationships) {
      const { source, target } = relation as { source: { tableId: string; fieldId: string }; target: { tableId: string; fieldId: string } };
      expect(known.has(`${source.tableId}.${source.fieldId}`)).toBe(true);
      expect(known.has(`${target.tableId}.${target.fieldId}`)).toBe(true);
    }
  });

  it("only references real fields inside calculated fields", () => {
    const known = knownFieldIds();
    const visit = (node: unknown): void => {
      if (Array.isArray(node)) return node.forEach(visit);
      if (node && typeof node === "object") {
        const record = node as Record<string, unknown>;
        if (typeof record.id === "string" && !("operator" in record)) expect(known.has(record.id)).toBe(true);
        Object.values(record).forEach(visit);
      }
    };
    expressions.forEach((expression) => visit(expression.expression));
  });
});

describe("default dashboard", () => {
  it("references only fields that exist", () => {
    const known = knownFieldIds();
    for (const id of referencedFieldIds()) expect(known.has(id), id).toBe(true);
  });

  it("has a page for every navigation tab", () => {
    expect(pages.map((page) => page.id)).toEqual(PAGES.map((page) => page.id));
  });

  it("places every widget inside the 24-track canvas without overlap", () => {
    for (const page of pages) {
      const ids = Object.keys(page.widgets);
      for (const id of ids) {
        const place = page.widgetLayout[id];
        expect(place, `${page.id}.${id}`).toBeDefined();
        expect(place.xTrack + place.xSpan).toBeLessThanOrEqual(24);
      }
      for (let i = 0; i < ids.length; i++) {
        for (let j = i + 1; j < ids.length; j++) {
          const a = page.widgetLayout[ids[i]], b = page.widgetLayout[ids[j]];
          const overlaps = a.xTrack < b.xTrack + b.xSpan && b.xTrack < a.xTrack + a.xSpan && a.yTrack < b.yTrack + b.ySpan && b.yTrack < a.yTrack + a.ySpan;
          expect(overlaps, `${page.id}: ${ids[i]} vs ${ids[j]}`).toBe(false);
        }
      }
    }
  });
});
