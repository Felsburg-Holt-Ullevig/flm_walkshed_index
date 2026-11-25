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
const status = (page: Page) => page.getByRole('status');

test('shows the shell and the default muted basemap', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const requested = await stubServices(page);
  await page.setViewportSize({ width: 1366, height: 800 });
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('FLM Walkshed Index');
  await expect(page.getByRole('group', { name: 'Basemap style' })).toBeVisible();
  await expect(page.getByRole('radio', { name: /^Muted/ })).toBeChecked();
  await expect(page.getByRole('checkbox', { name: /Walkshed labels/ })).toBeChecked();
  await expect(page.getByText(/^Build /)).toBeVisible();
  await expect(mapArea(page)).toHaveAttribute('data-basemap', 'oit-vector-muted');
  await expect(mapArea(page)).toHaveAttribute('data-basemap-state', 'ready');
  await expect(status(page)).toHaveText('Basemap style loaded: Muted.');
  await expect(page.locator('.maplibregl-ctrl-attrib')).toContainText('OpenStreetMap');
  await expect(page.locator('.maplibregl-ctrl-attrib')).toContainText('U.S. Census Bureau');
  expect(new Set(requested)).toEqual(new Set([VECTOR_HOST]));
  expect(errors).toEqual([]);

  // The scale bar stays visible and clear of the attribution line, which can wrap.
  const scale = await page.locator('.maplibregl-ctrl-scale').boundingBox();
  const credit = await page.locator('.maplibregl-ctrl-attrib').boundingBox();
  expect(scale && credit).toBeTruthy();
  if (scale && credit) expect(scale.y + scale.height).toBeLessThan(credit.y);
  await page.screenshot({ path: 'data/staging/prototype/shell-desktop.png' });
});

test('switches basemap styles and labels, and records them in the address', async ({ page }) => {
  await stubServices(page);
  await page.goto('/');
  await expect(mapArea(page)).toHaveAttribute('data-basemap-state', 'ready');
  const canvas = page.locator('.maplibregl-canvas');
  const muted = await canvas.screenshot();

  await page.getByRole('radio', { name: /^Dark/ }).check();
  await expect(mapArea(page)).toHaveAttribute('data-basemap', 'oit-vector-dark');
  await expect(status(page)).toHaveText('Basemap style loaded: Dark.');
  await expect(page).toHaveURL(/basemap=dark/);
  await expect.poll(async () => (await canvas.screenshot()).equals(muted)).toBe(false);

  await page.getByRole('checkbox', { name: /Walkshed labels/ }).uncheck();
  await expect(page).toHaveURL(/labels=original/);
  await expect(mapArea(page)).toHaveAttribute('data-basemap-state', 'ready');

  // A shared link reopens the same choices.
  await page.reload();
  await expect(page.getByRole('radio', { name: /^Dark/ })).toBeChecked();
  await expect(page.getByRole('checkbox', { name: /Walkshed labels/ })).not.toBeChecked();
});

test('loads the map engine and its worker from a subdirectory', async ({ page }) => {
  await stubServices(page);
  await page.goto('/review/');
  await expect(mapArea(page)).toHaveAttribute('data-basemap-state', 'ready');
});

test('offers alternatives when the basemap is unavailable', async ({ page }) => {
  await stubServices(page, { style: 'unavailable' });
  await page.goto('/');
  await expect(mapArea(page)).toHaveAttribute('data-basemap-state', 'unavailable');
  await expect(status(page)).toContainText(
    'Basemap unavailable (fetch_failed: vector basemap style returned HTTP 503)',
  );

  await page.getByRole('radio', { name: /^No basemap/ }).check();
  await expect(mapArea(page)).toHaveAttribute('data-basemap', 'none');
  await expect(status(page)).toHaveText('No basemap selected.');

  await page.getByRole('radio', { name: /^Map server images/ }).check();
  await expect(mapArea(page)).toHaveAttribute('data-basemap-state', 'ready');
});

test('reports basemap tiles that fail to load', async ({ page }) => {
  await stubServices(page, { tiles: 'failing' });
  await page.goto('/');
  await expect(mapArea(page)).toHaveAttribute('data-basemap-state', 'partial');
  await expect(status(page)).toContainText('did not load');
});

test('supports keyboard use of the panel and basemap choice', async ({ page }) => {
  await stubServices(page);
  await page.goto('/');
  await expect(mapArea(page)).toHaveAttribute('data-basemap-state', 'ready');

  await page.keyboard.press('Tab');
  const skip = page.getByRole('link', { name: 'Skip to map options' });
  await expect(skip).toBeFocused();
  await expect(skip).toBeInViewport();
  await page.keyboard.press('Enter');
  await expect(page.locator('#panel')).toBeFocused();

  await page.getByRole('radio', { name: /^Muted/ }).focus();
  await page.keyboard.press('ArrowDown');
  await expect(mapArea(page)).toHaveAttribute('data-basemap', 'oit-vector-dark');
  await expect(mapArea(page)).toHaveAttribute('data-basemap-state', 'ready');

  await page.getByRole('checkbox', { name: /Walkshed labels/ }).focus();
  await page.keyboard.press('Space');
  await expect(page).toHaveURL(/labels=original/);
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
    // The options start collapsed on narrow screens so the map is visible without scrolling.
    await expect(page.getByRole('radio', { name: /^Muted/ })).toBeHidden();
    const box = await mapArea(page).boundingBox();
    expect(box?.height ?? 0).toBeGreaterThan(300);
    expect(box?.y ?? Number.POSITIVE_INFINITY).toBeLessThan(300);
    await page.getByText('Map options', { exact: true }).click();
    await expect(page.getByRole('radio', { name: /^Muted/ })).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    await page.screenshot({ path: `data/staging/prototype/shell-${width}.png`, fullPage: true });
  }
});
