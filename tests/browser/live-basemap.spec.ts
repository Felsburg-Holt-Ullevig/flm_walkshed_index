import { expect, test } from '@playwright/test';

// Contacts the real State of Colorado services, so it runs only when FLM_LIVE_SERVICES=1 and
// never as part of the required checks. Results describe service availability and speed at the
// time of the run, not application correctness.
test.skip(!process.env.FLM_LIVE_SERVICES, 'Set FLM_LIVE_SERVICES=1 to contact live services.');

for (const [basemap, label] of [
  ['oit-vector', /Colorado state basemap Pre-built/],
  ['oit-raster', /map server images/],
] as const) {
  test(`live ${basemap} basemap loads at the fixture view`, async ({ page }) => {
    test.setTimeout(180000);
    const hosts = new Map<string, number>();
    const failed: string[] = [];
    page.on('requestfinished', (request) => {
      const host = new URL(request.url()).host;
      hosts.set(host, (hosts.get(host) ?? 0) + 1);
    });
    page.on('requestfailed', (request) => failed.push(request.url()));
    await page.setViewportSize({ width: 1366, height: 800 });
    await page.goto('/');
    const area = page.locator('.map-area');
    if (basemap !== 'oit-vector') {
      await expect(area).toHaveAttribute('data-basemap-state', /ready|partial|unavailable/, {
        timeout: 120000,
      });
      await page.getByRole('radio', { name: label }).check();
    }
    const started = Date.now();
    await expect(area).toHaveAttribute('data-basemap', basemap);
    await expect(area).toHaveAttribute('data-basemap-state', /ready|partial|unavailable/, {
      timeout: 150000,
    });
    const state = await area.getAttribute('data-basemap-state');
    console.log(
      JSON.stringify({
        basemap,
        state,
        secondsToSettle: (Date.now() - started) / 1000,
        status: await page.getByRole('status').textContent(),
        requestsByHost: Object.fromEntries(hosts),
        failedRequests: failed.length,
      }),
    );
    await page.screenshot({ path: `data/staging/prototype/live-${basemap}.png` });
    expect(state).toBe('ready');
  });
}
