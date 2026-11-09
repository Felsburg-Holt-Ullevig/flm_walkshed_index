import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';

for (const path of ['/', '/review/']) {
  test(`real package fetch and worker traversal at ${path}`, async ({ page }) => {
    page.on('pageerror', (error) => console.log('page error', error.message));
    await page.goto(path, { waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: 'Load package' }).click();
    await expect(page.getByRole('status')).toContainText('Loaded synthetic');
    console.log('load observation', await page.getByRole('status').textContent());
    await page.getByRole('button', { name: 'Calculate reachability' }).click();
    await expect(page.getByTestId('total')).toHaveText('Unique length: 150.000000 feet');
    const expected = JSON.parse(
      readFileSync(
        'data/generated/prototype/network-packages/_expected-results/synthetic-f01-task52-20261104-e.json',
        'utf8',
      ),
    );
    const actual = JSON.parse((await page.locator('pre').textContent()) ?? '');
    expect(actual.manifest_sha256).toBe(expected.manifest_sha256);
    expect(actual.graph_id).toBe(expected.graph_id);
    expect(actual.outputs.reached_nodes).toEqual(expected.outputs.reached_nodes);
    await page.screenshot({
      path: `data/staging/prototype/task53-${path === '/' ? 'root' : 'subdirectory'}-desktop.png`,
      fullPage: true,
    });
    console.log('compute observation', await page.getByRole('status').textContent());
    await page.getByLabel('Source node ID').fill('3');
    await page.getByRole('button', { name: 'Calculate reachability' }).click();
    await expect(page.getByTestId('total')).toHaveText('Unique length: 0.000000 feet');
    await page.getByLabel('Source node ID').fill('1');
    await page.getByLabel('Walking budget (seconds)').fill('0');
    await page.getByRole('button', { name: 'Calculate reachability' }).click();
    await expect(page.getByTestId('total')).toHaveText('Unique length: 0.000000 feet');
    await page.getByLabel('Walking budget (seconds)').fill('36.576');
    await page.getByLabel('Source node ID').fill('999');
    await page.getByRole('button', { name: 'Calculate reachability' }).click();
    await expect(page.getByRole('status')).toContainText('no_network');
    await page.route('**/nodes.json', (route) =>
      route.fulfill({ contentType: 'application/json', body: '{}' }),
    );
    await page.getByRole('button', { name: 'Load package' }).click();
    await expect(page.getByRole('status')).toContainText('integrity_mismatch');
    await expect(page.getByText('Active release:', { exact: false })).toContainText(
      'synthetic-f01',
    );
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.getByLabel('Source node ID').focus();
    await page.keyboard.press('Tab');
    await expect(page.getByLabel('Walking budget (seconds)')).toBeFocused();
    await page.screenshot({
      path: `data/staging/prototype/task53-${path === '/' ? 'root' : 'subdirectory'}-narrow.png`,
      fullPage: true,
    });
  });
}
