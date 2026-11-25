import { describe, expect, it } from 'vitest';
import type { BasemapStyle, LayerSpecification } from './basemap';
import { muteBasemapStyle, muteColor, parseColor } from './muted';

describe('parseColor', () => {
  it('reads the hex and rgb forms used by the state style', () => {
    expect(parseColor('#fff')).toEqual({ r: 255, g: 255, b: 255, a: 1 });
    expect(parseColor('#004DA8')).toEqual({ r: 0, g: 77, b: 168, a: 1 });
    expect(parseColor('#00000080')?.a).toBeCloseTo(0.502, 3);
    expect(parseColor('rgba(10, 20, 30, 0.5)')).toEqual({ r: 10, g: 20, b: 30, a: 0.5 });
  });

  it('rejects text that is not a colour', () => {
    expect(parseColor('{_name}')).toBeNull();
    expect(parseColor('match')).toBeNull();
    expect(parseColor('rgb(300, 0, 0)')).toBeNull();
  });
});

describe('muteColor', () => {
  it('converts to grey by perceived brightness and keeps transparency', () => {
    expect(muteColor('#00ff00', 0)).toBe('rgb(182, 182, 182)');
    expect(muteColor('rgba(0, 0, 0, 0.4)', 0)).toBe('rgba(0, 0, 0, 0.4)');
  });

  it('lightens towards white by the given share', () => {
    expect(muteColor('#000000', 0.5)).toBe('rgb(128, 128, 128)');
    expect(muteColor('#ffffff', 0.5)).toBe('rgb(255, 255, 255)');
  });
});

describe('muteBasemapStyle', () => {
  const style: BasemapStyle = {
    sources: {},
    layers: [
      {
        id: 'water',
        type: 'fill',
        source: 's',
        paint: { 'fill-color': '#0000ff', 'fill-opacity': 0.5 },
      },
      {
        id: 'roads',
        type: 'line',
        source: 's',
        paint: {
          'line-color': {
            stops: [
              [5, '#ff0000'],
              [12, '#000000'],
            ],
          },
        },
      },
      {
        id: 'labels',
        type: 'symbol',
        source: 's',
        layout: { 'text-field': '{_name}' },
        paint: { 'text-color': '#ff0000', 'text-halo-color': '#000000' },
      },
    ] as LayerSpecification[],
  };
  const paintOf = (result: BasemapStyle, index: number) =>
    (result.layers[index] as { paint: Record<string, unknown> }).paint;

  it('greys and lightens fills and lines, including zoom stops, and leaves other properties', () => {
    const result = muteBasemapStyle(style, 0.5);
    expect(paintOf(result, 0)).toEqual({ 'fill-color': 'rgb(137, 137, 137)', 'fill-opacity': 0.5 });
    expect(paintOf(result, 1)).toEqual({
      'line-color': {
        stops: [
          [5, 'rgb(155, 155, 155)'],
          [12, 'rgb(128, 128, 128)'],
        ],
      },
    });
  });

  it('keeps label text unlightened for contrast but lightens halos', () => {
    const result = muteBasemapStyle(style, 0.5);
    expect(paintOf(result, 2)).toEqual({
      'text-color': 'rgb(54, 54, 54)',
      'text-halo-color': 'rgb(128, 128, 128)',
    });
  });

  it('does not change the input style', () => {
    muteBasemapStyle(style, 0.5);
    expect(paintOf(style, 0)['fill-color']).toBe('#0000ff');
  });
});
