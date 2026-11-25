import { describe, expect, it } from 'vitest';
import type { BasemapStyle, LayerSpecification } from './basemap';
import { type BasemapVariant, styleVariant } from './variants';

// A small style using the state basemap's data layer names.
function stateStyle(): BasemapStyle {
  const layer = (id: string, type: string, sourceLayer: string, paint: object, layout?: object) =>
    ({
      id: `basemap/${id}`,
      type,
      source: 'basemap-oit-vector',
      'source-layer': sourceLayer,
      paint,
      ...(layout ? { layout } : {}),
    }) as unknown as LayerSpecification;
  return {
    sources: {},
    layers: [
      layer('forest', 'fill', 'National Forests', { 'fill-color': 'rgba(204,255,204,0.4)' }),
      layer('park', 'fill', 'Denver Parks', { 'fill-color': 'rgba(215,234,183,0.7)' }),
      layer('lake', 'fill', 'NHD Waterbodies', { 'fill-color': '#1462C3' }),
      layer('trail', 'line', 'COTREX', {
        'line-color': '#806A59',
        'line-width': {
          stops: [
            [14, 1],
            [18, 2],
          ],
        },
        'line-dasharray': [2, 2],
      }),
      layer('road', 'line', 'Local Roads', { 'line-color': '#B09881' }),
      layer('buildings', 'fill', 'OpenStreetMap Building Footprints', {
        'fill-color': 'rgba(204,204,204,0.4)',
      }),
      layer(
        'road-label',
        'symbol',
        'Local Roads/label',
        { 'text-color': '#000000', 'text-halo-color': '#FFFFFF' },
        { 'text-field': '{_name}' },
      ),
      layer(
        'shield',
        'symbol',
        'Highway - Labels/label',
        { 'text-color': '#FFFFFF' },
        { 'text-field': '{_name}', 'icon-image': 'Interstate' },
      ),
    ],
  };
}

type Painted = { id: string; type: string; paint: Record<string, unknown> };
const byId = (style: BasemapStyle, id: string) =>
  (style.layers as unknown as Painted[]).find((layer) => layer.id === `basemap/${id}`);
const ids = (style: BasemapStyle) => style.layers.map((layer) => layer.id.replace('basemap/', ''));

const VARIANTS: BasemapVariant[] = ['dark', 'contrast', 'minimal', 'walking', 'tinted'];

describe('styleVariant', () => {
  it.each(VARIANTS)('%s keeps highway shield labels and leaves the input unchanged', (variant) => {
    const input = stateStyle();
    const result = styleVariant(input, variant);
    expect(byId(result, 'shield')?.paint['text-color']).toBe('rgb(255, 255, 255)');
    expect(byId(input, 'road')?.paint['line-color']).toBe('#B09881');
  });

  it('dark puts a dark background first and draws labels light on dark halos', () => {
    const result = styleVariant(stateStyle(), 'dark');
    expect(result.layers[0]).toMatchObject({
      type: 'background',
      paint: { 'background-color': '#1d2026' },
    });
    expect(byId(result, 'road-label')?.paint).toEqual({
      'text-color': 'rgb(232, 232, 232)',
      'text-halo-color': 'rgb(29, 32, 38)',
    });
  });

  it('contrast removes land fills, keeps water and uses black labels with wide halos', () => {
    const result = styleVariant(stateStyle(), 'contrast');
    expect(ids(result)).not.toContain('forest');
    expect(ids(result)).not.toContain('park');
    expect(ids(result)).toContain('lake');
    expect(byId(result, 'road-label')?.paint['text-halo-width']).toBe(2);
    expect(byId(result, 'road-label')?.paint['text-color']).toBe('rgb(0, 0, 0)');
  });

  it('minimal hides public lands, trails and buildings but keeps parks, water and streets', () => {
    expect(ids(styleVariant(stateStyle(), 'minimal'))).toEqual([
      'park',
      'lake',
      'road',
      'road-label',
      'shield',
    ]);
  });

  it('walking keeps park colours and draws trails solid, green and wider', () => {
    const result = styleVariant(stateStyle(), 'walking');
    expect(byId(result, 'park')?.paint['fill-color']).toBe('rgba(215, 234, 183, 0.7)');
    expect(byId(result, 'trail')?.paint).toEqual({
      'line-color': 'rgb(27, 127, 59)',
      'line-width': {
        stops: [
          [14, 1.8],
          [18, 3.6],
        ],
      },
    });
    expect(byId(result, 'road')?.paint['line-color']).toMatch(/^rgb\((\d+), \1, \1\)$/);
  });

  it('tinted shifts greys towards blue', () => {
    const road = byId(styleVariant(stateStyle(), 'tinted'), 'road')?.paint['line-color'];
    const [r, , b] = String(road).match(/\d+/g)?.map(Number) ?? [];
    expect(b).toBeGreaterThan(r ?? 255);
  });
});
