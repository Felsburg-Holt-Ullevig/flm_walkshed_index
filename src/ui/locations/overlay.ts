import type { Location } from '../../domain/locations';
import type { OverlayStyle } from '../map/compose-style';

export const LOCATIONS_SOURCE_ID = 'app-locations';
export const LOCATION_MARKER_LAYER_ID = 'app/location-marker';
export const LOCATION_NUMBER_LAYER_ID = 'app/location-number';
const MARKER_FONT = 'Noto Sans Bold';

export function locationsGeoJSON(locations: readonly Location[], selectedId: string | null) {
  return {
    type: 'FeatureCollection' as const,
    features: locations.map((location, index) => ({
      type: 'Feature' as const,
      properties: { id: location.id, number: index + 1, selected: location.id === selectedId },
      geometry: { type: 'Point' as const, coordinates: [location.lng, location.lat] },
    })),
  };
}

/** Numbered markers drawn above basemap labels. Selection is shown by size and outline. */
export function locationsOverlay(
  locations: readonly Location[],
  selectedId: string | null,
  glyphs: string,
): OverlayStyle {
  return {
    sources: {
      [LOCATIONS_SOURCE_ID]: { type: 'geojson', data: locationsGeoJSON(locations, selectedId) },
    },
    belowLabels: [],
    onTop: [
      {
        id: LOCATION_MARKER_LAYER_ID,
        type: 'circle',
        source: LOCATIONS_SOURCE_ID,
        paint: {
          'circle-color': '#001970',
          'circle-radius': ['case', ['get', 'selected'], 14, 11],
          'circle-stroke-color': ['case', ['get', 'selected'], '#e57200', '#ffffff'],
          'circle-stroke-width': ['case', ['get', 'selected'], 4, 2],
        },
      },
      {
        id: LOCATION_NUMBER_LAYER_ID,
        type: 'symbol',
        source: LOCATIONS_SOURCE_ID,
        layout: {
          'text-field': ['to-string', ['get', 'number']],
          'text-font': [MARKER_FONT],
          'text-size': 11,
          'text-allow-overlap': true,
          'text-ignore-placement': true,
        },
        paint: { 'text-color': '#ffffff' },
      },
    ],
    glyphs,
  };
}
