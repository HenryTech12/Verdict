import { expect, test } from "@playwright/test";

// These tests drive the real UI against the real API in mock mode (see playwright.config.ts).
test.describe("Verdict dashboard", () => {
  test("simulator route runs Case B repeatedly", async ({ page }) => {
    await page.goto("/simulator");
    await expect(page.getByRole("heading", { name: "Scenario lab" })).toBeVisible();
    for (let i = 0; i < 2; i++) {
      await page.getByRole("button", { name: "Run Case B" }).click();
      await expect(page.getByText(/Case B created DSP-/)).toBeVisible();
    }
  });

  test("Case B: the agent chooses not to fight and refunds automatically", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /Case B/ }).first().click();
    await expect(page.getByText(/Case B complete/)).toBeVisible();
    const row = page.locator(".ag-row", { hasText: "Tunde A." }).first();
    await expect(row.getByText("Refunded")).toBeVisible();
    await row.click();
    await expect(page.getByText("Agent chose not to fight")).toBeVisible();
    await expect(page.getByText("Conflict detected")).toBeVisible();
  });

  test("Case C: guardrail forces approval, then approve submits the packet", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /Case C/ }).first().click();
    await expect(page.getByText(/Case C complete/)).toBeVisible();
    const row = page.locator(".ag-row", { hasText: "Mina Okafor" }).first();
    await expect(row.getByText("Awaiting approval")).toBeVisible();
    await row.click();
    await expect(page.getByText(/above your approval threshold/i)).toBeVisible();
    await page.getByRole("button", { name: /Approve Fight/ }).click();
    await expect(page.locator(".ag-row", { hasText: "Mina Okafor" }).first().getByText("Submitted")).toBeVisible();
  });
});
