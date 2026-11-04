import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:3000", trace: "on-first-retry" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    { command: "python -m uvicorn app.main:app --port 8000", cwd: "backend", env: { PAYPAL_MODE: "mock", LLM_PROVIDER: "mock" }, url: "http://127.0.0.1:8000/health", reuseExistingServer: true, timeout: 120_000 },
    { command: "npm run dev -- --hostname 127.0.0.1", cwd: ".", url: "http://127.0.0.1:3000", reuseExistingServer: true, timeout: 120_000 },
  ],
});
