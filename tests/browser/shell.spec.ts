import { expect, type Page, test } from '@playwright/test';

// The state services are replaced with small stand-ins so these checks do not depend on
// external availability. tests/browser/live-basemap.spec.ts exercises the real services.
const VECTOR_HOST = 'ti-cooit.img.arcgis.com';
const RASTER_HOST = 'gis.colorado.gov';
const STYLE = {
  version: 8,
  sources: { esri: { type: 'vector', url: '../../', minzoom: 0, maxzoom: 19 } },
  layers: [
    {
      id: 'Water',
      type: 'fill',
      source: 'esri',
      'source-layer': 'Water',
      paint: { 'fill-color': '#9cf' },
    },
  ],
};
// One grey pixel; MapLibre scales it to the tile.
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGO4e/cuAAUyApjDDfqPAAAAAElFTkSuQmCC',
  'base64',
);

interface StubOptions {
  style?: 'ok' | 'unavailable';
  tiles?: 'ok' | 'failing';
}

async function stubServices(page: Page, options: StubOptions = {}) {
  const requested: string[] = [];
  await page.route(
    (url) => url.hostname !== '127.0.0.1',
    (route) => {
      const url = new URL(route.request().url());
      requested.push(url.hostname);
      if (url.hostname === VECTOR_HOST && url.pathname.endsWith('/resources/styles/root.json'))
        return options.style === 'unavailable'
          ? route.fulfill({ status: 503, body: 'Service unavailable' })
          : route.fulfill({ contentType: 'application/json', body: JSON.stringify(STYLE) });
      if (url.hostname === VECTOR_HOST && url.pathname.endsWith('.pbf'))
        return options.tiles === 'failing'
          ? route.fulfill({ status: 500, body: 'Error' })
          : route.fulfill({ contentType: 'application/x-protobuf', body: Buffer.alloc(0) });
      if (url.hostname === RASTER_HOST && url.pathname.endsWith('/export'))
        return route.fulfill({ contentType: 'image/png', body: PNG });
      return route.abort();
    },
  );
  return requested;
}

const mapArea = (page: Page) => page.locator('.map-area');

test('shows the shell, basemap and fixture overlays', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const requested = await stubServices(page);
  await page.setViewportSize({ width: 1366, height: 800 });
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('FLM Walkshed Index');
  for (const name of ['Stations', 'Walksheds', 'Index analysis', 'Results and exports'])
    await expect(page.getByRole('heading', { level: 3, name })).toBeVisible();
  await expect(mapArea(page)).toHaveAttribute('data-basemap-state', 'ready');
  await expect(page.getByRole('status')).toHaveText('Basemap loaded: Colorado state basemap.');
  await expect(page.locator('.maplibregl-ctrl-attrib')).toContainText('OpenStreetMap');
  expect(new Set(requested)).toEqual(new Set([VECTOR_HOST]));
  expect(errors).toEqual([]);
  await page.screenshot({ path: 'data/staging/prototype/shell-desktop.png' });

  // Hiding the fixtures changes the rendered map; showing them restores it.
  const canvas = page.locator('.maplibregl-canvas');
  const withFixtures = await canvas.screenshot();
  await page.getByLabel('Show illustrative fixture shapes').uncheck();
  await expect.poll(async () => (await canvas.screenshot()).equals(withFixtures)).toBe(false);
  await page.getByLabel('Show illustrative fixture shapes').check();
  await expect.poll(async () => (await canvas.screenshot()).equals(withFixtures)).toBe(true);
});

test('loads the map engine and its worker from a subdirectory', async ({ page }) => {
  await stubServices(page);
  await page.goto('/review/');
  await expect(mapArea(page)).toHaveAttribute('data-basemap-state', 'ready');
});

test('keeps overlays and offers alternatives when the basemap is unavailable', async ({ page }) => {
  await stubServices(page, { style: 'unavailable' });
  await page.goto('/');
  await expect(mapArea(page)).toHaveAttribute('data-basemap-state', 'unavailable');
  await expect(page.getByRole('status')).toContainText(
    'Basemap unavailable (fetch_failed: vector basemap style returned HTTP 503)',
  );
  await expect(page.getByLabel('Show illustrative fixture shapes')).toBeChecked();

  await page.getByRole('radio', { name: /No basemap/ }).check();
  await expect(mapArea(page)).toHaveAttribute('data-basemap', 'none');
  await expect(page.getByRole('status')).toHaveText('No basemap selected.');

  await page.getByRole('radio', { name: /map server images/ }).check();
  await expect(mapArea(page)).toHaveAttribute('data-basemap-state', 'ready');
  await expect(page.getByText(`Basemap requests go to ${RASTER_HOST}.`)).toBeVisible();
});

test('reports basemap tiles that fail to load', async ({ page }) => {
  await stubServices(page, { tiles: 'failing' });
  await page.goto('/');
  await expect(mapArea(page)).toHaveAttribute('data-basemap-state', 'partial');
  await expect(page.getByRole('status')).toContainText('did not load');
});

test('supports keyboard use of the panel and basemap choice', async ({ page }) => {
  await stubServices(page);
  await page.goto('/');
  await expect(mapArea(page)).toHaveAttribute('data-basemap-state', 'ready');

  await page.keyboard.press('Tab');
  const skip = page.getByRole('link', { name: 'Skip to analysis panel' });
  await expect(skip).toBeFocused();
  await expect(skip).toBeInViewport();
  await page.keyboard.press('Enter');
  await expect(page.locator('#panel')).toBeFocused();

  await page.keyboard.press('Tab');
  const toggle = page.getByRole('button', { name: 'Hide panel' });
  await expect(toggle).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('button', { name: 'Show panel' })).toHaveAttribute(
    'aria-expanded',
    'false',
  );
  await expect(page.getByRole('heading', { name: 'Stations' })).toBeHidden();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('button', { name: 'Hide panel' })).toHaveAttribute(
    'aria-expanded',
    'true',
  );

  await page.getByRole('radio', { name: /Colorado state basemap Pre-built/ }).focus();
  await page.keyboard.press('ArrowDown');
  await expect(mapArea(page)).toHaveAttribute('data-basemap', 'oit-raster');
  await expect(mapArea(page)).toHaveAttribute('data-basemap-state', 'ready');
});

test('reflows without horizontal scrolling at narrow widths', async ({ page }) => {
  await stubServices(page);
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 800 });
    await page.goto('/');
    await expect(mapArea(page)).toHaveAttribute('data-basemap-state', 'ready');
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    // The panel starts closed on narrow screens so the map is visible without scrolling.
    await expect(page.getByRole('button', { name: 'Show panel' })).toBeVisible();
    const box = await mapArea(page).boundingBox();
    expect(box?.height ?? 0).toBeGreaterThan(300);
    expect(box?.y ?? Number.POSITIVE_INFINITY).toBeLessThan(300);
    await page.getByRole('button', { name: 'Show panel' }).click();
    await expect(page.getByRole('heading', { name: 'Stations' })).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    await page.screenshot({ path: `data/staging/prototype/shell-${width}.png`, fullPage: true });
  }
});
