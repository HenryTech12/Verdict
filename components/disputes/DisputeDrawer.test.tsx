import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import DisputeDrawer, { type DisputeDetail } from "./DisputeDrawer";
import { api } from "@/lib/api/client";

const detail: DisputeDetail = { id: "DSP-C", customer_name: "Mina Okafor", amount: "480.00", currency: "USD", status: "AWAITING_APPROVAL", deadline: "2030-01-01T00:00:00Z", simulated: true, decision: { policy_decision: "FIGHT", guardrail_rule: "AMOUNT_ABOVE_APPROVAL_THRESHOLD", final_action: "ESCALATE" }, assessment: { evidence_items: [], conflicts: [], checklist_score: 0.9, win_likelihood: 0.9, confidence: 0.9, rationale: "Strong evidence", packet_draft: "packet" }, audit: [] };

describe("DisputeDrawer approval flow", () => {
  afterEach(() => vi.restoreAllMocks());

  it("confirms and approves the requested action", async () => {
    const approve = vi.spyOn(api, "approve").mockResolvedValue(detail as unknown as Record<string, unknown>);
    render(<DisputeDrawer detail={detail} onClose={vi.fn()} onUpdated={vi.fn()} onAction={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(screen.getByText("Submit evidence for $480.00")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(approve).toHaveBeenCalledWith("DSP-C", "");
  });
});
