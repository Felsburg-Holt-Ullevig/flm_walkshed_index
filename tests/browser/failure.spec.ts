import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';

const root = 'data/generated/prototype/network-packages/synthetic-f01-task52-20261104-e/';
for (const [name, code] of [
  ['version', 'unsupported_version'],
  ['html', 'invalid_content'],
  ['missing', 'fetch_failed'],
  ['mixed', 'release_mismatch'],
  ['cost', 'invalid_graph'],
] as const) {
  test(`rejects ${name} candidate and preserves current graph`, async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Load package' }).click();
    await expect(page.getByRole('status')).toContainText('Loaded synthetic');
    const manifest = JSON.parse(readFileSync(`${root}manifest.json`, 'utf8'));
    if (name === 'version') manifest.schema_version = 'unsupported';
    if (name === 'missing')
      await page.route('**/nodes.json', (route) => route.fulfill({ status: 404, body: 'Missing' }));
    if (name === 'mixed' || name === 'cost') {
      const file = name === 'mixed' ? 'nodes' : 'segments';
      const value = JSON.parse(readFileSync(`${root}${file}.json`, 'utf8'));
      if (name === 'mixed') value.release_id = 'different-release';
      else value.segments[0].base_seconds += 1;
      const body = JSON.stringify(value);
      manifest.files[file].bytes = Buffer.byteLength(body);
      manifest.files[file].sha256 = createHash('sha256').update(body).digest('hex');
      await page.route(`**/${file}.json`, (route) =>
        route.fulfill({ contentType: 'application/json', body }),
      );
    }
    await page.route('**/manifest.json', (route) =>
      route.fulfill({
        contentType: name === 'html' ? 'text/html' : 'application/json',
        body: name === 'html' ? '<html>fallback</html>' : JSON.stringify(manifest),
      }),
    );
    await page.getByRole('button', { name: 'Load package' }).click();
    await expect(page.getByRole('status')).toContainText(code);
    await page.getByRole('button', { name: 'Calculate reachability' }).click();
    await expect(page.getByTestId('total')).toContainText('150.000000');
  });
}
test('cancels a pending candidate', async ({ page }) => {
  await page.goto('/');
  await page.route('**/manifest.json', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 500));
    await route.abort();
  });
  await page.getByRole('button', { name: 'Load package' }).click();
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('cancelled');
});
