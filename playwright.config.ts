import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests/browser',
  timeout: 120000,
  // The basemap service worker would answer requests the tests stub with page.route.
  use: { baseURL: 'http://127.0.0.1:4174', browserName: 'chromium', serviceWorkers: 'block' },
  webServer: {
    command: 'node scripts/review-server.mjs',
    url: 'http://127.0.0.1:4174',
    reuseExistingServer: true,
  },
});
