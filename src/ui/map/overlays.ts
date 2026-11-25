import type { LayerSpecification } from '../../adapters/basemaps/basemap';
import type { OverlayStyle } from './compose-style';
import { FIXTURE_WALKSHEDS } from './fixtures';

// CDOT brand colours with at least 3:1 contrast against the basemap background. Fixture B also
// uses a dashed outline so the two shapes are distinguishable without colour.
export const WALKSHED_STYLE = {
  A: { color: '#001970', dashed: false },
  B: { color: '#c3002f', dashed: true },
} as const;

type FillLayer = Extract<LayerSpecification, { type: 'fill' }>;
type ColorValue = NonNullable<NonNullable<FillLayer['paint']>['fill-color']>;

const visibility = (visible: boolean): 'visible' | 'none' => (visible ? 'visible' : 'none');
const colorById: ColorValue = [
  'match',
  ['get', 'id'],
  'A',
  WALKSHED_STYLE.A.color,
  WALKSHED_STYLE.B.color,
];

export function buildOverlays(options: { fixturesVisible: boolean }): OverlayStyle {
  const layout = { visibility: visibility(options.fixturesVisible) };
  const fills: LayerSpecification[] = [
    {
      id: 'fixture-walksheds/fill',
      type: 'fill',
      source: 'fixture-walksheds',
      layout,
      paint: { 'fill-color': colorById, 'fill-opacity': 0.16 },
    },
    {
      id: 'fixture-walksheds/outline-solid',
      type: 'line',
      source: 'fixture-walksheds',
      filter: ['==', ['get', 'dashed'], false],
      layout: { ...layout, 'line-join': 'round' },
      paint: { 'line-color': colorById, 'line-width': 2.5 },
    },
    {
      id: 'fixture-walksheds/outline-dashed',
      type: 'line',
      source: 'fixture-walksheds',
      filter: ['==', ['get', 'dashed'], true],
      layout: { ...layout, 'line-join': 'round' },
      paint: { 'line-color': colorById, 'line-width': 2.5, 'line-dasharray': [3, 1.5] },
    },
  ];
  const stations: LayerSpecification[] = [
    {
      id: 'fixture-stations/marker',
      type: 'circle',
      source: 'fixture-stations',
      layout,
      paint: {
        'circle-radius': 7,
        'circle-color': '#ffffff',
        'circle-stroke-width': 3,
        'circle-stroke-color': colorById,
      },
    },
  ];
  return {
    sources: {
      'fixture-walksheds': {
        type: 'geojson',
        data: {
          type: 'FeatureCollection',
          features: FIXTURE_WALKSHEDS.map((w) => ({
            type: 'Feature',
            properties: { id: w.id, dashed: WALKSHED_STYLE[w.id].dashed },
            geometry: { type: 'Polygon', coordinates: [w.ring] },
          })),
        },
      },
      'fixture-stations': {
        type: 'geojson',
        data: {
          type: 'FeatureCollection',
          features: FIXTURE_WALKSHEDS.map((w) => ({
            type: 'Feature',
            properties: { id: w.id },
            geometry: { type: 'Point', coordinates: w.station },
          })),
        },
      },
    },
    belowLabels: fills,
    onTop: stations,
  };
}
