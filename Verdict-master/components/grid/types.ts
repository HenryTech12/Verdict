import type { Dispute } from "@/lib/api/client";

/** A dispute row, or the synthetic full-width detail row inserted beneath an expanded dispute
 * (master/detail is an Enterprise feature, so the Community grid uses full-width rows instead). */
export type GridRow = Dispute & { __detail?: boolean; parent?: string; sig?: string };
export type GridContext = { onChanged: () => void; openDrawer: (id: string) => void; expanded: Set<string> };
