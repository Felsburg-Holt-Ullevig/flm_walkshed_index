import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { PLACE_TIERS, placeLayers } from './places';

interface PlaceFeature {
  geometry: { type: string; coordinates: [number, number] };
  properties: { name: string; kind: string; tier: number; population?: number };
}

const file = JSON.parse(readFileSync('public/data/place-labels.geojson', 'utf8')) as {
  features: PlaceFeature[];
};

describe('place-label file', () => {
  it('has a named label point inside Colorado for every place', () => {
    for (const { geometry, properties } of file.features) {
      expect(geometry.type).toBe('Point');
      const [lon, lat] = geometry.coordinates;
      expect(lon).toBeGreaterThan(-109.1);
      expect(lon).toBeLessThan(-102.0);
      expect(lat).toBeGreaterThan(36.9);
      expect(lat).toBeLessThan(41.1);
      expect(properties.name.length).toBeGreaterThan(0);
    }
  });

  it('has a drawing tier for every kind and tier present in the file', () => {
    const drawn = new Set(PLACE_TIERS.map((entry) => `${entry.kind}/${entry.tier}`));
    for (const { properties } of file.features)
      expect(drawn).toContain(`${properties.kind}/${properties.tier}`);
  });

  it('places city labels at their centres, not at arbitrary interior points', () => {
    const at = (name: string) =>
      file.features.find((f) => f.properties.name === name && f.properties.kind === 'municipality')
        ?.geometry.coordinates ?? [0, 0];
    const km = ([lon, lat]: number[], [lon2, lat2]: number[]) =>
      Math.hypot(((lon ?? 0) - (lon2 ?? 0)) * 85.3, ((lat ?? 0) - (lat2 ?? 0)) * 111);
    // Denver's Civic Center; the Census internal point was about 9 km east, near the airport arm.
    expect(km(at('Denver'), [-104.99, 39.739])).toBeLessThan(2);
    // West of Aurora's eastern plains, near its original town centre along Colfax.
    expect(at('Aurora')[0]).toBeLessThan(-104.8);
  });

  it('puts Denver and Aurora in the top municipal tier', () => {
    const tierOf = (name: string) =>
      file.features.find((f) => f.properties.name === name && f.properties.kind === 'municipality')
        ?.properties.tier;
    expect(tierOf('Denver')).toBe(1);
    expect(tierOf('Aurora')).toBe(1);
  });
});

describe('placeLayers', () => {
  it('draws municipalities in bold capitals and neighbourhoods in italic capitals', () => {
    const layout = (id: string) => {
      const found = placeLayers().find(({ layer }) => layer.id === `basemap/places-${id}`);
      if (!found) throw Error(`No layer ${id}`);
      return (found.layer as unknown as { layout: Record<string, unknown> }).layout;
    };
    expect(layout('municipality-1')['text-font']).toEqual(['Noto Sans Bold']);
    expect(layout('municipality-1')['text-transform']).toBe('uppercase');
    expect(layout('neighborhood-3')['text-font']).toEqual(['Noto Sans Italic']);
    expect(layout('community-3')['text-transform']).toBe('none');
  });
});
