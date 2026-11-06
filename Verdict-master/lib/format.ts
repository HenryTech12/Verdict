import type { Dispute } from "@/lib/api/client";

export const pretty = (value: string | null | undefined) => (value ? value.replaceAll("_", " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase()) : "Pending");
export const money = (value: string | number, currency = "USD") => new Intl.NumberFormat("en-US", { style: "currency", currency }).format(Number(value));

export type Urgency = "expired" | "urgent" | "soon" | "ok";

export function timeLeft(deadline: string, now = Date.now()): { label: string; level: Urgency; ms: number } {
  const ms = new Date(deadline).getTime() - now;
  if (ms <= 0) return { label: "Expired", level: "expired", ms };
  const minutes = Math.floor(ms / 60000), hours = Math.floor(minutes / 60), days = Math.floor(hours / 24);
  const label = days >= 2 ? `${days}d ${hours % 24}h` : hours >= 1 ? `${hours}h ${minutes % 60}m` : `${minutes}m`;
  return { label, level: hours < 24 ? "urgent" : hours < 72 ? "soon" : "ok", ms };
}

export const STATUSES = ["NEW", "ASSESSING", "AWAITING_APPROVAL", "EVIDENCE_SUBMITTED", "REFUNDED", "RESOLVED", "EXPIRED"] as const;
export const STATUS_LABEL: Record<string, string> = { NEW: "New", ASSESSING: "Assessing", AWAITING_APPROVAL: "Awaiting approval", EVIDENCE_SUBMITTED: "Submitted", REFUNDED: "Refunded", RESOLVED: "Resolved", EXPIRED: "Expired" };

/** Cases that need a human come first (soonest deadline first), then everything else newest first. */
export function sortDisputes(rows: Dispute[]): Dispute[] {
  return [...rows].sort((a, b) => {
    const aw = a.status === "AWAITING_APPROVAL" ? 0 : 1, bw = b.status === "AWAITING_APPROVAL" ? 0 : 1;
    if (aw !== bw) return aw - bw;
    if (aw === 0) return new Date(a.deadline).getTime() - new Date(b.deadline).getTime();
    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
  });
}
