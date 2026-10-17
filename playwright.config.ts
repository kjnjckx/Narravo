import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: 'tests/e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 30000,
  use: {
    baseURL: 'http://127.0.0.1:1421',
    viewport: { width: 1440, height: 950 },
    screenshot: 'only-on-failure',
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE }
      : {},
  },
  webServer: {
    command: 'pnpm --filter @narravo/desktop dev --port 1421',
    url: 'http://127.0.0.1:1421',
    reuseExistingServer: false,
    env: { VITE_TEST_BRIDGE: '1' },
  },
});
