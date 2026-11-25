import type { LayerSpecification, SourceSpecification } from './basemap';
import { LOCAL_FONT_BOLD, LOCAL_FONT_ITALIC, LOCAL_FONT_REGULAR } from './oit-vector';

/**
 * Place-name labels from public/data/place-labels.geojson (built by
 * scripts/build-place-labels.mjs). The state basemap's own place names carry no type or
 * population and stop at zoom 10; these replace them with a hierarchy:
 *
 * - municipalities: bold spaced capitals, sized by population tier;
 * - unincorporated communities (census-designated places): regular, mixed case;
 * - Denver neighbourhoods (OpenStreetMap): italic spaced capitals, lighter, at walkshed zooms;
 *   smaller named areas only from zoom 14.
 */
export const PLACES_SOURCE_ID = 'basemap-places';
export const PLACES_LAYER_PREFIX = 'basemap/places-';

export const PLACES_ATTRIBUTION = 'Places: U.S. Census Bureau, USGS GNIS, OpenStreetMap';

type Kind = 'municipality' | 'community' | 'neighborhood';

interface PlaceTier {
  kind: Kind;
  /** Population tier for places; for neighbourhoods, 2 is district scale and 3 smaller areas. */
  tier: 1 | 2 | 3;
  minzoom: number;
  maxzoom: number;
  /** Text size at zoom 8, 12 and 16. */
  sizes: [number, number, number];
  color: string;
  /** Collision priority within the label preset (see labels.ts). */
  priority: number;
}

export const PLACE_TIERS: readonly PlaceTier[] = [
  {
    kind: 'municipality',
    tier: 1,
    minzoom: 7,
    maxzoom: 16,
    sizes: [13, 17, 18],
    color: '#2b2b2b',
    priority: 4.8,
  },
  {
    kind: 'municipality',
    tier: 2,
    minzoom: 9,
    maxzoom: 16,
    sizes: [11, 14, 15],
    color: '#333333',
    priority: 4.7,
  },
  {
    kind: 'municipality',
    tier: 3,
    minzoom: 10,
    maxzoom: 16,
    sizes: [10, 12, 13],
    color: '#3d3d3d',
    priority: 4.6,
  },
  {
    kind: 'community',
    tier: 1,
    minzoom: 8,
    maxzoom: 15,
    sizes: [12, 15, 16],
    color: '#3d3d3d',
    priority: 4.5,
  },
  {
    kind: 'community',
    tier: 2,
    minzoom: 9,
    maxzoom: 15,
    sizes: [11, 13, 14],
    color: '#454545',
    priority: 4.4,
  },
  {
    kind: 'community',
    tier: 3,
    minzoom: 11,
    maxzoom: 15,
    sizes: [10, 11.5, 12.5],
    color: '#4d4d4d',
    priority: 4.3,
  },
  {
    kind: 'neighborhood',
    tier: 2,
    minzoom: 12,
    maxzoom: 17,
    sizes: [10, 11, 12.5],
    color: '#666666',
    priority: 3.5,
  },
  {
    kind: 'neighborhood',
    tier: 3,
    minzoom: 14,
    maxzoom: 17,
    sizes: [9, 10, 11],
    // Lightest grey that keeps 4.5:1 contrast on white.
    color: '#767676',
    priority: 3.4,
  },
];

export function placesSource(url: string): SourceSpecification {
  return { type: 'geojson', data: url, attribution: PLACES_ATTRIBUTION } as SourceSpecification;
}

export function placeLayers(): { layer: LayerSpecification; priority: number }[] {
  return PLACE_TIERS.map((entry) => {
    const spaced = entry.kind !== 'community';
    const font =
      entry.kind === 'municipality'
        ? LOCAL_FONT_BOLD
        : entry.kind === 'neighborhood'
          ? LOCAL_FONT_ITALIC
          : LOCAL_FONT_REGULAR;
    const [z8, z12, z16] = entry.sizes;
    const layer = {
      id: `${PLACES_LAYER_PREFIX}${entry.kind}-${entry.tier}`,
      type: 'symbol',
      source: PLACES_SOURCE_ID,
      minzoom: entry.minzoom,
      maxzoom: entry.maxzoom,
      filter: ['all', ['==', ['get', 'kind'], entry.kind], ['==', ['get', 'tier'], entry.tier]],
      layout: {
        'text-field': ['get', 'name'],
        'text-font': [font],
        'text-size': ['interpolate', ['linear'], ['zoom'], 8, z8, 12, z12, 16, z16],
        'text-transform': spaced ? 'uppercase' : 'none',
        'text-letter-spacing': spaced ? 0.12 : 0,
        'text-max-width': 7,
        'text-padding': 6,
        // Larger places win collisions within a tier (the file is sorted by population too).
        'symbol-sort-key': ['-', 0, ['coalesce', ['get', 'population'], 0]],
      },
      paint: {
        'text-color': entry.color,
        'text-halo-color': '#ffffff',
        'text-halo-width': 1.5,
      },
    } as unknown as LayerSpecification;
    return { layer, priority: entry.priority };
  });
}
