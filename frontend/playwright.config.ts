import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end suite. Needs the e2e stack (fake Drive, captured mail, test DB):
 *   docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d api web
 *   npx playwright test
 * Full flows run in Chromium; the capture and gallery screens (@xb) also run in
 * Firefox, WebKit and two mobile viewports.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1, // one shared backend; every test resets it
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 20_000 },
  reporter: [["list"], ["json", { outputFile: "test-results/e2e-results.json" }]],
  use: { baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000", trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] }, grep: /@xb/ },
    { name: "webkit", use: { ...devices["Desktop Safari"] }, grep: /@xb/ },
    { name: "mobile-chrome", use: { ...devices["Pixel 7"] }, grep: /@xb|@visual/ },
    { name: "mobile-safari", use: { ...devices["iPhone 14"] }, grep: /@xb/ },
  ],
});
