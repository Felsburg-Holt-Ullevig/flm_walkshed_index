import type { BasemapStyle, LayerSpecification } from './basemap';
import { LOCAL_FONT_BOLD } from './oit-vector';
import { PLACES_SOURCE_ID, placeLayers, placesSource } from './places';

/**
 * Label settings for reviewing walksheds (roughly zoom 12-17), applied on top of any style of the
 * state vector basemap. The state tiles' label data carries only a name, a label class and a
 * shield length, so labels are chosen by data layer, not by road type. Local road and trail names
 * exist in the tiles from zoom 14 although the published style waits until 15.9. The tiles' own
 * place names have no type or population and stop at zoom 10, so they are replaced by the
 * place-name layers in places.ts when a place-label file is supplied.
 */
export type LabelPreset = 'walkshed' | 'original';

type Layer = Record<string, unknown> & {
  type: string;
  minzoom?: number;
  maxzoom?: number;
  filter?: unknown;
  layout?: Record<string, unknown>;
  paint?: Record<string, unknown>;
};

/** Collision priority, lowest first; MapLibre places labels from later layers first. */
const PRIORITY: [RegExp, number][] = [
  [/^(ColoradoCensusCounties|Neighboring States)\/label$/, 0],
  [/(Wilderness|BLM|Grasslands|Fish and Wildlife|Forests|National Parks|Wildlife Areas)/, 0],
  [/^NHD /, 1],
  [/^Municipal Boundaries\/label$|^Colorado City Point Locations$/, 2],
  [/^Local Roads\/label$/, 3],
  [/^(COTREX\/label|Denver Parks\/label|State Parks\/label)$/, 4],
  [/^Major Roads\/label$/, 5],
  [/^Highway - Labels\/label$/, 6],
];

/** Labels of regional context, hidden once zoomed in to walkshed scale. */
const REGIONAL =
  /^(ColoradoCensusCounties\/label|National Wilderness Areas\/label|National Forests\/label|National Parks\/label|National Grasslands\/label|US Fish and Wildlife Lands\/label|BLM Wilderness Study Areas\/label|State Wildlife Areas\/label)$/;

/** Placeholder names in the road label data that are not useful on the map. */
export const SUPPRESSED_ROAD_NAMES = ['Private Rd'];

/** Text size growing with zoom, in pixels. */
const grow = (from: number, to: number) => ['interpolate', ['linear'], ['zoom'], 14, from, 17, to];

function priorityOf(source: string): number {
  for (const [pattern, rank] of PRIORITY) if (pattern.test(source)) return rank;
  return 1;
}

function withoutNames(filter: unknown): unknown {
  const exclude = ['!in', '_name', ...SUPPRESSED_ROAD_NAMES];
  return filter === undefined ? exclude : ['all', filter, exclude];
}

/** Halo width: CDOT's 2.7 px halos are thinned; widths set by a style (such as 2) are kept. */
function halo(layer: Layer): void {
  const width = layer.paint?.['text-halo-width'];
  if (typeof width === 'number' && width > 2.5 && layer.paint) layer.paint['text-halo-width'] = 1.5;
}

function roadLabel(layer: Layer, sizes: [number, number], spacing: number, bold: boolean): void {
  layer.minzoom = Math.min(layer.minzoom ?? 14, 14);
  layer.filter = withoutNames(layer.filter);
  layer.layout ??= {};
  const layout = layer.layout;
  layout['text-size'] = grow(...sizes);
  layout['symbol-spacing'] = spacing;
  layout['text-padding'] = 4;
  layout['text-max-angle'] = 30;
  if (bold) layout['text-font'] = [LOCAL_FONT_BOLD];
  halo(layer);
}

function adjust(layer: Layer, source: string): void {
  if (layer.type !== 'symbol') return;
  switch (source) {
    case 'Local Roads/label':
      roadLabel(layer, [10.5, 12.5], 800, false);
      return;
    case 'Major Roads/label':
      roadLabel(layer, [12, 14], 700, true);
      return;
    case 'Highway - Labels/label':
      layer.layout ??= {};
      layer.layout['symbol-spacing'] = 550;
      return;
    case 'COTREX/label':
      layer.minzoom = 14;
      halo(layer);
      return;
  }
  if (REGIONAL.test(source)) layer.maxzoom = Math.min(layer.maxzoom ?? 24, 12);
  if (
    layer.layout?.['symbol-placement'] === undefined &&
    layer.layout?.['text-field'] !== undefined
  )
    layer.layout['text-max-width'] = 8;
}

/** State basemap place names, replaced by the place-name layers. */
const STATE_PLACE_NAMES = /^(Colorado City Point Locations|Municipal Boundaries\/label)$/;

export interface LabelPresetOptions {
  /** Absolute URL of public/data/place-labels.geojson; omit to keep the state place names. */
  placesUrl?: string;
}

/** Applies a label preset to a state vector basemap style. `original` returns it unchanged. */
export function applyLabelPreset(
  style: BasemapStyle,
  preset: LabelPreset,
  options: LabelPresetOptions = {},
): BasemapStyle {
  if (preset === 'original') return style;
  const others: LayerSpecification[] = [];
  const labels: { layer: LayerSpecification; rank: number; index: number }[] = [];
  (style.layers as unknown as Layer[]).forEach((original, index) => {
    const source = String(original['source-layer'] ?? '');
    const isLabel = original.type === 'symbol' && original.layout?.['text-field'] !== undefined;
    if (!isLabel) {
      others.push(original as unknown as LayerSpecification);
      return;
    }
    if (options.placesUrl && STATE_PLACE_NAMES.test(source)) return;
    const layer = structuredClone(original);
    adjust(layer, source);
    labels.push({ layer: layer as unknown as LayerSpecification, rank: priorityOf(source), index });
  });
  let sources = style.sources;
  if (options.placesUrl) {
    sources = { ...sources, [PLACES_SOURCE_ID]: placesSource(options.placesUrl) };
    placeLayers().forEach(({ layer, priority }, offset) => {
      labels.push({ layer, rank: priority, index: style.layers.length + offset });
    });
  }
  labels.sort((a, b) => a.rank - b.rank || a.index - b.index);
  return { ...style, sources, layers: [...others, ...labels.map((entry) => entry.layer)] };
}
