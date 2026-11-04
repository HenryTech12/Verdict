import { expect, test } from "@playwright/test";

test.describe("Verdict simulator", () => {
  test("runs Case B repeatedly and shows the simulator route", async ({ page }) => {
    await page.goto("/simulator");
    await expect(page.getByRole("heading", { name: "Scenario lab" })).toBeVisible();
    await page.getByRole("button", { name: "Run Case B" }).click();
    await expect(page.getByText(/Created DSP-/)).toBeVisible();
    await page.getByRole("button", { name: "Run Case B" }).click();
    await expect(page.getByText(/Created DSP-/)).toBeVisible();
  });
});
