import { describe, expect, it } from 'vitest';
import { BasemapError } from './basemap';
import {
  adaptEsriVectorStyle,
  LINE_LABEL_OFFSET_EMS,
  LOCAL_FONT_BOLD,
  LOCAL_FONT_ITALIC,
  LOCAL_FONT_REGULAR,
  loadOitVectorBasemap,
  localFontFor,
  OIT_VECTOR_SOURCE_ID,
  prefetchOitVectorStyle,
} from './oit-vector';

const SERVICE = 'https://tiles.example.test/arcgis/rest/services/Base/VectorTileServer';

// Synthetic style with the structure ArcGIS VectorTileServer publishes at
// resources/styles/root.json: relative resources and a source URL that is not TileJSON.
function esriStyle() {
  return {
    version: 8,
    sprite: '../sprites/sprite',
    glyphs: '../fonts/{fontstack}/{range}.pbf',
    sources: {
      esri: {
        type: 'vector',
        url: '../../',
        bounds: [-109.7, 36.0, -100.3, 42.3],
        minzoom: 0,
        maxzoom: 19,
        scheme: 'xyz',
      },
    },
    layers: [
      {
        id: 'Water',
        type: 'fill',
        source: 'esri',
        'source-layer': 'Water',
        paint: { 'fill-color': '#9cf' },
      },
      {
        id: 'Roads/label',
        type: 'symbol',
        source: 'esri',
        'source-layer': 'Roads/label',
        layout: { 'text-field': '{_name}', 'text-font': ['Sans Regular'] },
      },
    ],
  };
}

describe('adaptEsriVectorStyle', () => {
  it('resolves resources and replaces the source with an explicit tile template', () => {
    const result = adaptEsriVectorStyle(esriStyle(), SERVICE, 'Credit');
    expect(result.sprite).toBe(
      'https://tiles.example.test/arcgis/rest/services/Base/VectorTileServer/resources/sprites/sprite',
    );
    expect(result.glyphs).toBe(
      'https://tiles.example.test/arcgis/rest/services/Base/VectorTileServer/resources/fonts/{fontstack}/{range}.pbf',
    );
    expect(result.sources).toEqual({
      [OIT_VECTOR_SOURCE_ID]: {
        type: 'vector',
        tiles: [`${SERVICE}/tile/{z}/{y}/{x}.pbf`],
        attribution: 'Credit',
        minzoom: 0,
        maxzoom: 19,
        bounds: [-109.7, 36.0, -100.3, 42.3],
      },
    });
  });

  it('prefixes layer IDs, points layers at the renamed source and keeps their order', () => {
    const result = adaptEsriVectorStyle(esriStyle(), SERVICE, 'Credit');
    expect(result.layers.map((layer) => layer.id)).toEqual([
      'basemap/Water',
      'basemap/Roads/label',
    ]);
    for (const layer of result.layers)
      expect('source' in layer && layer.source).toBe(OIT_VECTOR_SOURCE_ID);
  });

  it('moves plain line labels off the road line and leaves other labels unchanged', () => {
    const input = esriStyle();
    const lineLabel = (layout: Record<string, unknown>, id: string) => ({
      id,
      type: 'symbol',
      source: 'esri',
      'source-layer': 'Roads/label',
      layout: { 'text-field': '{_name}', 'symbol-placement': 'line', ...layout },
    });
    const style = {
      ...input,
      layers: [
        ...input.layers,
        lineLabel({}, 'street'),
        lineLabel({ 'symbol-placement': 'line-center' }, 'centre'),
        lineLabel({ 'icon-image': 'shield' }, 'shield'),
        lineLabel({ 'text-offset': [0, 1] }, 'already-offset'),
      ],
    };
    const offsets = Object.fromEntries(
      adaptEsriVectorStyle(style, SERVICE, 'Credit').layers.map((layer) => [
        layer.id,
        layer.layout && 'text-offset' in layer.layout ? layer.layout['text-offset'] : undefined,
      ]),
    );
    expect(offsets).toEqual({
      'basemap/Water': undefined,
      'basemap/Roads/label': undefined,
      'basemap/street': [0, -LINE_LABEL_OFFSET_EMS],
      'basemap/centre': [0, -LINE_LABEL_OFFSET_EMS],
      'basemap/shield': undefined,
      'basemap/already-offset': [0, 1],
    });
  });

  it('does not modify the input document', () => {
    const input = esriStyle();
    const before = structuredClone(input);
    adaptEsriVectorStyle(input, SERVICE, 'Credit');
    expect(input).toEqual(before);
  });

  const rejected: [string, (style: ReturnType<typeof esriStyle>) => unknown][] = [
    ['a non-object', () => []],
    ['another specification version', (s) => ({ ...s, version: 7 })],
    ['no sources', (s) => ({ ...s, sources: {} })],
    ['two sources', (s) => ({ ...s, sources: { ...s.sources, other: s.sources.esri } })],
    ['a raster source', (s) => ({ ...s, sources: { esri: { type: 'raster' } } })],
    ['no layers', (s) => ({ ...s, layers: [] })],
    ['a layer without an ID', (s) => ({ ...s, layers: [{ type: 'fill', source: 'esri' }] })],
    ['duplicate layer IDs', (s) => ({ ...s, layers: [s.layers[0], s.layers[0]] })],
    [
      'an unknown layer type',
      (s) => ({ ...s, layers: [{ id: 'x', type: 'model', source: 'esri' }] }),
    ],
    [
      'a layer on an unknown source',
      (s) => ({ ...s, layers: [{ id: 'x', type: 'fill', source: 'other' }] }),
    ],
    ['labels without glyphs', (s) => ({ ...s, glyphs: undefined })],
    ['an insecure glyphs URL', (s) => ({ ...s, glyphs: 'http://x.test/{fontstack}/{range}.pbf' })],
    ['a glyphs URL without placeholders', (s) => ({ ...s, glyphs: '../fonts/all.pbf' })],
    ['a sprite array', (s) => ({ ...s, sprite: [{ id: 'a', url: 'b' }] })],
    [
      'invalid bounds',
      (s) => ({ ...s, sources: { esri: { ...s.sources.esri, bounds: [0, 0, 'x', 1] } } }),
    ],
  ];
  for (const [name, mutate] of rejected) {
    it(`rejects ${name}`, () => {
      expect(() => adaptEsriVectorStyle(mutate(esriStyle()), SERVICE, 'Credit')).toThrow(
        /^invalid_content: /,
      );
    });
  }
});

describe('loadOitVectorBasemap', () => {
  const signal = new AbortController().signal;

  it('requests the published root style without credentials', async () => {
    const calls: [string, RequestInit | undefined][] = [];
    const fetchImpl = (async (url: string, init?: RequestInit) => {
      calls.push([url, init]);
      return new Response(JSON.stringify(esriStyle()), { status: 200 });
    }) as typeof fetch;
    const result = await loadOitVectorBasemap(SERVICE, 'Credit', signal, fetchImpl);
    expect(calls[0]?.[0]).toBe(`${SERVICE}/resources/styles/root.json`);
    expect(calls[0]?.[1]?.credentials).toBe('omit');
    expect(result.layers).toHaveLength(2);
  });

  it('reports HTTP failures as fetch_failed', async () => {
    const fetchImpl = (async () => new Response('busy', { status: 503 })) as typeof fetch;
    const failure = loadOitVectorBasemap(SERVICE, 'Credit', signal, fetchImpl);
    await expect(failure).rejects.toBeInstanceOf(BasemapError);
    await expect(failure).rejects.toThrow('fetch_failed: vector basemap style returned HTTP 503');
  });

  it('reports network failures as fetch_failed', async () => {
    const fetchImpl = (async () => {
      throw new TypeError('Failed to fetch');
    }) as typeof fetch;
    await expect(loadOitVectorBasemap(SERVICE, 'Credit', signal, fetchImpl)).rejects.toThrow(
      /^fetch_failed: /,
    );
  });

  it('reports non-JSON responses as invalid_content', async () => {
    const fetchImpl = (async () => new Response('<html></html>')) as typeof fetch;
    await expect(loadOitVectorBasemap(SERVICE, 'Credit', signal, fetchImpl)).rejects.toThrow(
      'invalid_content: vector basemap style is not JSON',
    );
  });

  it('propagates cancellation instead of reporting a failure', async () => {
    const controller = new AbortController();
    const fetchImpl = (async () => {
      controller.abort();
      throw new DOMException('aborted', 'AbortError');
    }) as typeof fetch;
    await expect(
      loadOitVectorBasemap(SERVICE, 'Credit', controller.signal, fetchImpl),
    ).rejects.toThrow('aborted');
  });

  it('uses a prefetched style request once instead of fetching again', async () => {
    const service = `${SERVICE}/prefetch`;
    let calls = 0;
    const fetchImpl = (async () => {
      calls++;
      return new Response(JSON.stringify(esriStyle()), { status: 200 });
    }) as typeof fetch;
    prefetchOitVectorStyle(service, fetchImpl);
    prefetchOitVectorStyle(service, fetchImpl);
    await loadOitVectorBasemap(service, 'Credit', signal, fetchImpl);
    expect(calls).toBe(1);
    await loadOitVectorBasemap(service, 'Credit', signal, fetchImpl);
    expect(calls).toBe(2);
  });

  it('reports a failed prefetched request as fetch_failed', async () => {
    const service = `${SERVICE}/prefetch-fail`;
    const fetchImpl = (async () => new Response('busy', { status: 503 })) as typeof fetch;
    prefetchOitVectorStyle(service, fetchImpl);
    await expect(loadOitVectorBasemap(service, 'Credit', signal, fetchImpl)).rejects.toThrow(
      'fetch_failed: vector basemap style returned HTTP 503',
    );
  });
});

describe('local label fonts', () => {
  const LOCAL = 'https://app.example.test/fonts/{fontstack}/{range}.pbf';

  it('maps published font names to the nearest local style', () => {
    expect(localFontFor('Avenir Next LT Pro Regular')).toBe(LOCAL_FONT_REGULAR);
    expect(localFontFor('Tahoma Regular')).toBe(LOCAL_FONT_REGULAR);
    expect(localFontFor('Avenir Next LT Pro Italic')).toBe(LOCAL_FONT_ITALIC);
    expect(localFontFor('Avenir Next LT Pro Medium Italic')).toBe(LOCAL_FONT_ITALIC);
    expect(localFontFor('Avenir Next LT Pro Medium')).toBe(LOCAL_FONT_BOLD);
  });

  it('replaces the glyph URL and every label font when local glyphs are given', () => {
    const result = adaptEsriVectorStyle(esriStyle(), SERVICE, 'Credit', { localGlyphs: LOCAL });
    expect(result.glyphs).toBe(LOCAL);
    const label = result.layers.find((layer) => layer.type === 'symbol') as {
      layout: Record<string, unknown>;
    };
    expect(label.layout['text-font']).toEqual([LOCAL_FONT_REGULAR]);
  });

  it('leaves the published fonts unchanged without local glyphs', () => {
    const result = adaptEsriVectorStyle(esriStyle(), SERVICE, 'Credit');
    const label = result.layers.find((layer) => layer.type === 'symbol') as {
      layout: Record<string, unknown>;
    };
    expect(label.layout['text-font']).toEqual(['Sans Regular']);
  });
});
