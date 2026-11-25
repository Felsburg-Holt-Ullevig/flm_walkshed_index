import { describe, expect, it } from 'vitest';
import type { BasemapStyle } from '../../adapters/basemaps/basemap';
import { BACKGROUND_LAYER_ID, composeStyle, NO_OVERLAYS, type OverlayStyle } from './compose-style';

const vectorBasemap: BasemapStyle = {
  sources: { 'basemap-v': { type: 'vector', tiles: ['https://x.test/{z}/{x}/{y}.pbf'] } },
  layers: [
    { id: 'basemap/water', type: 'fill', source: 'basemap-v', 'source-layer': 'w' },
    { id: 'basemap/roads', type: 'line', source: 'basemap-v', 'source-layer': 'r' },
    {
      id: 'basemap/labels',
      type: 'symbol',
      source: 'basemap-v',
      'source-layer': 'l',
      layout: { 'text-field': 'x' },
    },
    { id: 'basemap/later-fill', type: 'fill', source: 'basemap-v', 'source-layer': 'p' },
  ],
  sprite: 'https://x.test/sprite',
  glyphs: 'https://x.test/{fontstack}/{range}.pbf',
};

const emptySource = {
  type: 'geojson',
  data: { type: 'FeatureCollection', features: [] },
} as const;
const overlays: OverlayStyle = {
  sources: { s: emptySource },
  belowLabels: [{ id: 'walkshed', type: 'fill', source: 's' }],
  onTop: [{ id: 'station', type: 'circle', source: 's' }],
};

describe('composeStyle', () => {
  it('places walksheds beneath the first basemap label and stations on top', () => {
    const style = composeStyle(vectorBasemap, overlays);
    expect(style.layers.map((layer) => layer.id)).toEqual([
      BACKGROUND_LAYER_ID,
      'basemap/water',
      'basemap/roads',
      'walkshed',
      'basemap/labels',
      'basemap/later-fill',
      'station',
    ]);
    expect(style.sprite).toBe(vectorBasemap.sprite);
    expect(style.glyphs).toBe(vectorBasemap.glyphs);
    expect(Object.keys(style.sources)).toEqual(['basemap-v', 's']);
  });

  it('places all overlays above a basemap that has no labels', () => {
    const raster: BasemapStyle = {
      sources: { 'basemap-r': { type: 'raster', tiles: ['https://x.test/{z}'] } },
      layers: [{ id: 'basemap/r', type: 'raster', source: 'basemap-r' }],
    };
    const style = composeStyle(raster, overlays);
    expect(style.layers.map((layer) => layer.id)).toEqual([
      BACKGROUND_LAYER_ID,
      'basemap/r',
      'walkshed',
      'station',
    ]);
    expect(style.glyphs).toBeUndefined();
  });

  it('keeps every overlay when no basemap is available', () => {
    const style = composeStyle(null, overlays);
    expect(style.layers.map((layer) => layer.id)).toEqual([
      BACKGROUND_LAYER_ID,
      'walkshed',
      'station',
    ]);
    expect(Object.keys(style.sources)).toEqual(['s']);
  });

  it('keeps the same overlays across every basemap', () => {
    const ids = (basemap: BasemapStyle | null) =>
      composeStyle(basemap, overlays)
        .layers.map((layer) => layer.id)
        .filter((id) => !id.startsWith('basemap') && id !== BACKGROUND_LAYER_ID);
    expect(ids(vectorBasemap)).toEqual(ids(null));
    expect(ids(null)).toEqual(['walkshed', 'station']);
  });

  it('draws only the background and basemap when there are no overlays', () => {
    const style = composeStyle(vectorBasemap, NO_OVERLAYS);
    expect(style.layers.map((layer) => layer.id)).toEqual([
      BACKGROUND_LAYER_ID,
      ...vectorBasemap.layers.map((layer) => layer.id),
    ]);
  });

  it('rejects overlay IDs reserved for the basemap', () => {
    expect(() =>
      composeStyle(null, {
        ...overlays,
        onTop: [{ id: 'basemap/x', type: 'circle', source: 's' }],
      }),
    ).toThrow('reserved');
    expect(() =>
      composeStyle(null, { ...overlays, sources: { 'basemap-x': emptySource } }),
    ).toThrow('reserved');
  });
});
