import type { Page } from '@playwright/test';

// The state services are replaced with small stand-ins so these checks do not depend on
// external availability. tests/browser/live-basemap.spec.ts exercises the real services.
export const VECTOR_HOST = 'ti-cooit.img.arcgis.com';
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

export async function stubServices(page: Page, options: StubOptions = {}) {
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
