import { describe, expect, it } from "vitest";
import type { Dispute } from "@/lib/api/client";
import { pretty, sortDisputes, timeLeft } from "@/lib/format";

const NOW = Date.parse("2026-11-05T12:00:00Z");
const hours = (h: number) => new Date(NOW + h * 3600_000).toISOString();

describe("timeLeft", () => {
  it("flags urgency by hours remaining", () => {
    expect(timeLeft(hours(-1), NOW)).toMatchObject({ level: "expired", label: "Expired" });
    expect(timeLeft(hours(6), NOW)).toMatchObject({ level: "urgent", label: "6h 0m" });
    expect(timeLeft(hours(48), NOW).level).toBe("soon");
    expect(timeLeft(hours(24 * 10), NOW)).toMatchObject({ level: "ok", label: "10d 0h" });
    expect(timeLeft(hours(0.5), NOW).label).toBe("30m");
  });
});

describe("sortDisputes", () => {
  const row = (id: string, status: string, deadline: string, created: string) => ({ id, status, deadline, created_at: created }) as Dispute;
  it("puts awaiting-approval cases first by soonest deadline, then newest first", () => {
    const rows = [row("old", "REFUNDED", hours(100), hours(-50)), row("later", "AWAITING_APPROVAL", hours(40), hours(-1)), row("new", "EVIDENCE_SUBMITTED", hours(90), hours(-2)), row("urgent", "AWAITING_APPROVAL", hours(5), hours(-3))];
    expect(sortDisputes(rows).map((r) => r.id)).toEqual(["urgent", "later", "new", "old"]);
  });
});

describe("pretty", () => {
  it("humanizes enum values", () => {
    expect(pretty("AWAITING_APPROVAL")).toBe("Awaiting approval");
    expect(pretty(null)).toBe("Pending");
  });
});
