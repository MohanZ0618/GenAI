import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "tests/browser",
  workers: 1,
  timeout: 45000,
  use: {
    baseURL: "http://127.0.0.1:4311",
    headless: true,
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:4311/api/health",
    timeout: 90000,
    reuseExistingServer: false,
    env: {
      PORT: "4311",
      FINTRACE_MODE: "fixture",
      FINTRACE_STORAGE_DIR: `.local/browser-tests-${Date.now()}`,
    },
  },
});
