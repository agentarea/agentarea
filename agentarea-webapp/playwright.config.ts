import { defineConfig, devices } from "@playwright/test";

const webPort = process.env.PLAYWRIGHT_WEB_PORT ?? "3100";
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? `http://localhost:${webPort}`;
const isCi = Boolean(process.env.CI);

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: isCi,
  retries: isCi ? 2 : 0,
  workers: 1,
  reporter: isCi ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium-real-stack",
      testMatch: /.*\.real\.spec\.ts/,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      // AI-driven (Stagehand) specs. Stagehand manages its own local browser,
      // so these tests use no Playwright `page` fixture - the project exists for
      // grouping/reporting and a dedicated `--project` filter.
      name: "chromium-ai-stack",
      testMatch: /.*\.ai\.spec\.ts/,
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: process.env.PLAYWRIGHT_REUSE_SERVER
    ? undefined
    : {
        command:
          `API_URL=${process.env.API_URL ?? "http://localhost:8000"} ORY_ADMIN_URL=${process.env.ORY_ADMIN_URL ?? "http://localhost:4434"} ORY_SDK_URL=${process.env.ORY_SDK_URL ?? "http://localhost:4433"} ORY_BROWSER_URL=${process.env.ORY_BROWSER_URL ?? "http://localhost:4433"} pnpm exec next dev --webpack --hostname 0.0.0.0 --port ${webPort}`,
        url: baseURL,
        reuseExistingServer: !isCi,
        timeout: 120_000,
      },
});
