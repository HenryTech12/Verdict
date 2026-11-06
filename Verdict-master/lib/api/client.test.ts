import { describe, expect, it, vi } from "vitest";
import { api } from "./client";

describe("API client", () => {
  it("parses the standard error shape", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: "INVALID_STATE", message: "Already resolved", details: {} } }), { status: 409 })));
    await expect(api.getApprovals()).rejects.toMatchObject({ status: 409, code: "INVALID_STATE", message: "Already resolved" });
  });
});
