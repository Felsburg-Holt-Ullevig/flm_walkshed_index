import { describe, expect, it } from 'vitest';
import type { BasemapStyle, LayerSpecification } from './basemap';
import { applyLabelPreset } from './labels';
import { LOCAL_FONT_BOLD } from './oit-vector';

type Layer = {
  id: string;
  type: string;
  minzoom?: number;
  maxzoom?: number;
  filter?: unknown;
  layout?: Record<string, unknown>;
  paint?: Record<string, unknown>;
};

function label(id: string, sourceLayer: string, extra: Partial<Layer> = {}): LayerSpecification {
  return {
    id,
    type: 'symbol',
    source: 'basemap-oit-vector',
    'source-layer': sourceLayer,
    layout: { 'text-field': '{_name}', ...(extra.layout ?? {}) },
    paint: { 'text-halo-width': 2.66667, ...(extra.paint ?? {}) },
    ...(extra.minzoom !== undefined ? { minzoom: extra.minzoom } : {}),
    ...(extra.maxzoom !== undefined ? { maxzoom: extra.maxzoom } : {}),
    ...(extra.filter !== undefined ? { filter: extra.filter } : {}),
  } as unknown as LayerSpecification;
}

function style(): BasemapStyle {
  return {
    sources: {},
    layers: [
      { id: 'road', type: 'line', source: 's', 'source-layer': 'Local Roads' },
      label('shield', 'Highway - Labels/label', {
        layout: { 'icon-image': 'x', 'symbol-spacing': 288 },
        filter: ['==', '_label_class', 1],
      }),
      label('park', 'Denver Parks/label', { minzoom: 13.6 }),
      label('local', 'Local Roads/label', { minzoom: 15.85 }),
      label('major', 'Major Roads/label', { minzoom: 12.85 }),
      label('county', 'ColoradoCensusCounties/label', { minzoom: 8 }),
      label('trail', 'COTREX/label', { minzoom: 15.85 }),
    ] as LayerSpecification[],
  };
}

const find = (s: BasemapStyle, id: string) =>
  (s.layers as unknown as Layer[]).find((layer) => layer.id === id) as Layer;

describe('applyLabelPreset', () => {
  it('returns the style unchanged for the original preset', () => {
    const input = style();
    expect(applyLabelPreset(input, 'original')).toBe(input);
  });

  it('orders labels by priority after all other layers, shields last', () => {
    expect(applyLabelPreset(style(), 'walkshed').layers.map((layer) => layer.id)).toEqual([
      'road',
      'county',
      'local',
      'park',
      'trail',
      'major',
      'shield',
    ]);
  });

  it('shows local road and trail names from zoom 14 and hides placeholder names', () => {
    const result = applyLabelPreset(style(), 'walkshed');
    expect(find(result, 'local').minzoom).toBe(14);
    expect(find(result, 'trail').minzoom).toBe(14);
    expect(find(result, 'major').minzoom).toBe(12.85);
    expect(find(result, 'local').filter).toEqual(['!in', '_name', 'Private Rd']);
  });

  it('sizes major roads larger and bold, with wider spacing and thinner halos', () => {
    const result = applyLabelPreset(style(), 'walkshed');
    const major = find(result, 'major');
    expect(major.layout?.['text-font']).toEqual([LOCAL_FONT_BOLD]);
    expect(major.layout?.['text-size']).toEqual([
      'interpolate',
      ['linear'],
      ['zoom'],
      14,
      12,
      17,
      14,
    ]);
    expect(major.layout?.['symbol-spacing']).toBe(700);
    expect(find(result, 'local').paint?.['text-halo-width']).toBe(1.5);
    expect(find(result, 'local').layout?.['text-font']).toBeUndefined();
  });

  it('spaces shields further apart and keeps their filter', () => {
    const shield = find(applyLabelPreset(style(), 'walkshed'), 'shield');
    expect(shield.layout?.['symbol-spacing']).toBe(550);
    expect(shield.filter).toEqual(['==', '_label_class', 1]);
  });

  it('hides regional labels above zoom 12 and wraps point labels', () => {
    const result = applyLabelPreset(style(), 'walkshed');
    expect(find(result, 'county').maxzoom).toBe(12);
    expect(find(result, 'park').layout?.['text-max-width']).toBe(8);
  });

  it('replaces the state place names with the place-name layers when a file is given', () => {
    const input = style();
    input.layers.push(label('cities', 'Colorado City Point Locations', { maxzoom: 10 }));
    const url = 'https://app.example.test/data/place-labels.geojson';
    const result = applyLabelPreset(input, 'walkshed', { placesUrl: url });
    const ids = result.layers.map((layer) => layer.id);
    expect(ids).not.toContain('cities');
    expect(result.sources['basemap-places']).toMatchObject({ type: 'geojson', data: url });
    // Neighbourhoods rank below trails and parks; municipalities below major roads only.
    expect(ids.indexOf('basemap/places-neighborhood-3')).toBeLessThan(ids.indexOf('park'));
    expect(ids.indexOf('basemap/places-municipality-1')).toBeGreaterThan(ids.indexOf('trail'));
    expect(ids.indexOf('basemap/places-municipality-1')).toBeLessThan(ids.indexOf('major'));
    expect(ids.slice(-1)).toEqual(['shield']);
  });

  it('keeps the state place names without a place-label file', () => {
    const input = style();
    input.layers.push(label('cities', 'Colorado City Point Locations', { maxzoom: 10 }));
    expect(applyLabelPreset(input, 'walkshed').layers.map((layer) => layer.id)).toContain('cities');
  });

  it('keeps a halo width a style set deliberately', () => {
    const input = style();
    (find(input, 'local').paint as Record<string, unknown>)['text-halo-width'] = 2;
    expect(find(applyLabelPreset(input, 'walkshed'), 'local').paint?.['text-halo-width']).toBe(2);
  });
});
