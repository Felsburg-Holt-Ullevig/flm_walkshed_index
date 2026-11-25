import { expect, type Page, test } from '@playwright/test';
import { stubServices } from './stubs';

const items = (page: Page) => page.locator('.location-list li');
const ready = (page: Page) =>
  expect(page.locator('.map-area')).toHaveAttribute('data-basemap-state', 'ready');

test.beforeEach(async ({ page }) => {
  await stubServices(page);
  await page.setViewportSize({ width: 1366, height: 800 });
  await page.goto('/');
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await ready(page);
});

test('adds locations on the map and at the centre, and keeps them after reload', async ({
  page,
}) => {
  const add = page.getByRole('button', { name: 'Add on map' });
  await add.click();
  await expect(add).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('status')).toContainText('Click the map to add a location');
  const map = page.locator('.maplibregl-canvas');
  await map.click({ position: { x: 300, y: 300 } });
  await map.click({ position: { x: 500, y: 400 } });
  await page.keyboard.press('Escape');
  await expect(add).toHaveAttribute('aria-pressed', 'false');
  await map.click({ position: { x: 700, y: 200 } });
  await expect(items(page)).toHaveCount(2);

  await page.getByRole('button', { name: 'Add at centre' }).click();
  await expect(items(page)).toHaveCount(3);
  await expect(page.getByRole('heading', { name: /Locations/ })).toContainText('3 of 100');
  await page.screenshot({ path: 'data/staging/prototype/locations-desktop.png' });

  await page.reload();
  await ready(page);
  await expect(items(page)).toHaveCount(3);
  await expect(items(page).nth(2)).toContainText('Location 3');
});

test('selects, drags, edits, deletes, undoes and redoes', async ({ page }) => {
  await page.getByRole('button', { name: 'Add at centre' }).click();
  const row = items(page).first();
  await expect(row).toHaveAttribute('data-selected', 'true');
  const coords = row.locator('.location-coords');
  const start = await coords.textContent();

  // Drag the marker from the map centre.
  const box = await page.locator('.maplibregl-canvas').boundingBox();
  if (!box) throw Error('no map');
  const cx = box.x + box.width / 2;
  const cy = box.y + box.height / 2;
  await page.mouse.move(cx, cy);
  await page.mouse.down();
  await page.mouse.move(cx + 60, cy + 40, { steps: 5 });
  await page.mouse.up();
  await expect(coords).not.toHaveText(start ?? '');
  await expect(items(page)).toHaveCount(1);
  await expect(page.getByRole('button', { name: 'Undo: move Location 1' })).toBeEnabled();
  await page.getByRole('button', { name: /^Undo/ }).click();
  await expect(coords).toHaveText(start ?? '');
  await page.getByRole('button', { name: /^Redo/ }).click();
  await expect(coords).not.toHaveText(start ?? '');

  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  await expect(page.getByLabel('Name')).toBeFocused();
  await page.getByLabel('Name').fill('Union Station');
  await page.getByLabel('Latitude').fill('39.7530');
  await page.getByLabel('Longitude').fill('-105.0002');
  await page.keyboard.press('Enter');
  await expect(row).toContainText('Union Station');
  await expect(row).toContainText('39.75300, -105.00020');

  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  await page.getByLabel('Latitude').fill('51.5');
  await page.getByRole('button', { name: 'Save' }).click();
  await expect(page.getByRole('alert')).toContainText('in or near Colorado');
  await page.getByRole('button', { name: 'Cancel' }).click();

  await page.getByRole('button', { name: 'Delete' }).click();
  await expect(items(page)).toHaveCount(0);
  await page.locator('body').press('Control+z');
  await expect(items(page)).toHaveCount(1);
  await page.locator('body').press('Control+Shift+z');
  await expect(items(page)).toHaveCount(0);
});

test('clears all locations with an undo offer', async ({ page }) => {
  const centre = page.getByRole('button', { name: 'Add at centre' });
  await centre.click();
  await centre.click();
  await page.getByRole('button', { name: 'Clear' }).click();
  await expect(items(page)).toHaveCount(0);
  const status = page.getByRole('status');
  await expect(status).toContainText('Cleared 2 locations.');
  await status.getByRole('button', { name: 'Undo' }).click();
  await expect(items(page)).toHaveCount(2);
});

test('works from the keyboard and at phone width', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await page.reload();
  await ready(page);
  await page.getByRole('button', { name: 'Add at centre' }).focus();
  await page.keyboard.press('Enter');
  await page.keyboard.press('Enter');
  await expect(items(page)).toHaveCount(2);
  await items(page).first().getByRole('button').first().focus();
  await page.keyboard.press('Enter');
  await expect(items(page).first()).toHaveAttribute('data-selected', 'true');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({ path: 'data/staging/prototype/locations-390.png', fullPage: true });
});
