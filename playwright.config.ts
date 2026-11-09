import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests/browser',
  timeout: 120000,
  use: { baseURL: 'http://127.0.0.1:4174', browserName: 'chromium' },
  webServer: {
    command: 'node scripts/review-server.mjs',
    url: 'http://127.0.0.1:4174',
    reuseExistingServer: true,
  },
});
