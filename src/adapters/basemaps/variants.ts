import type { BasemapStyle, LayerSpecification } from './basemap';
import { BASEMAP_LAYER_PREFIX } from './basemap';
import { parseColor, type Rgba } from './muted';

/**
 * Alternative looks for the state vector basemap, made by rewriting the published style as it
 * loads. Layers are recognised by their tile data layer (`source-layer`), which is more stable
 * than the style's layer IDs. The tiles contain roads, rail, trails (COTREX), water, parks and
 * public lands, municipal and county boundaries, city points and building footprints; they have
 * no sidewalks, crossings or transit stops.
 */
export type BasemapVariant = 'dark' | 'contrast' | 'minimal' | 'walking' | 'tinted';

type Layer = Record<string, unknown> & {
  type: string;
  paint?: Record<string, unknown>;
  layout?: Record<string, unknown>;
};

/** Colour of one paint property; `key` is the property name, such as `text-halo-color`. */
type Recolor = (color: Rgba, key: string, layer: Layer) => Rgba;

interface VariantRules {
  /** Map background colour; the application's light grey shows when omitted. */
  background?: string;
  /** Data layers removed entirely. */
  hide?: (sourceLayer: string, layer: Layer) => boolean;
  recolor: Recolor;
  /** Further changes to a layer after recolouring. */
  adjust?: (layer: Layer, sourceLayer: string) => void;
}

// Data layer groups in the state basemap.
const WATER = /^NHD /;
const PARKS = /^(Denver Parks|State Lands\/State Parks|State Parks)(\/label)?$/;
const TRAILS = /^COTREX/;
const OTHER_PUBLIC_LANDS =
  /^(National Wilderness Areas|BLM Lands|National Grasslands|US Fish and Wildlife Lands|BLM Wilderness Study Areas|State Wildlife Areas|National Forests|National Parks)(\/label)?$/;

const clamp = (v: number) => Math.max(0, Math.min(255, Math.round(v)));
const luma = (c: Rgba) => 0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b;
const grey = (v: number, a: number): Rgba => ({ r: clamp(v), g: clamp(v), b: clamp(v), a });
const rgb = (r: number, g: number, b: number, a = 1): Rgba => ({ r, g, b, a });
/** Mixes `from` towards `to`; t = 0 gives `from`, 1 gives `to`. */
const mix = (from: Rgba, to: Rgba, t: number): Rgba => ({
  r: clamp(from.r + (to.r - from.r) * t),
  g: clamp(from.g + (to.g - from.g) * t),
  b: clamp(from.b + (to.b - from.b) * t),
  a: from.a,
});
const WHITE = rgb(255, 255, 255);
const format = (c: Rgba) =>
  c.a === 1 ? `rgb(${c.r}, ${c.g}, ${c.b})` : `rgba(${c.r}, ${c.g}, ${c.b}, ${c.a})`;

const isText = (key: string) => key === 'text-color';
const isHalo = (key: string) => key === 'text-halo-color';
/** Labels drawn on an icon (such as Interstate numbers on shields) keep their colours. */
const onIcon = (layer: Layer) => layer.layout?.['icon-image'] !== undefined;

/** Grey of the same brightness, moved `lighten` of the way to white (the muted basemap). */
function muted(c: Rgba, key: string, lighten: number): Rgba {
  const l = luma(c);
  return isText(key) ? grey(l, c.a) : grey(l + (255 - l) * lighten, c.a);
}

function recolorValue(value: unknown, fn: (c: Rgba) => Rgba): unknown {
  if (typeof value === 'string') {
    const color = parseColor(value);
    return color ? format(fn(color)) : value;
  }
  if (Array.isArray(value)) return value.map((item) => recolorValue(item, fn));
  if (typeof value === 'object' && value !== null)
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, recolorValue(item, fn)]),
    );
  return value;
}

/** Multiplies a width given as a number or as zoom stops; other expressions are left alone. */
function scaleWidth(value: unknown, factor: number): unknown {
  if (typeof value === 'number') return value * factor;
  if (typeof value === 'object' && value !== null && 'stops' in value) {
    const stops = (value as { stops: unknown }).stops;
    if (Array.isArray(stops))
      return {
        ...value,
        stops: stops.map((stop) =>
          Array.isArray(stop) && typeof stop[1] === 'number' ? [stop[0], stop[1] * factor] : stop,
        ),
      };
  }
  return value;
}

const RULES: Record<BasemapVariant, VariantRules> = {
  // Light features become dark and dark lines light; water stays faintly blue.
  dark: {
    background: '#1d2026',
    recolor: (c, key, layer) => {
      if (onIcon(layer)) return c;
      if (isHalo(key)) return rgb(29, 32, 38, c.a);
      const l = luma(c) / 255;
      if (isText(key)) return grey(232 - l * 80, c.a);
      if (WATER.test(String(layer['source-layer']))) return rgb(38, 62, 92, c.a);
      return grey(42 + (1 - l) * 140, c.a);
    },
  },
  // White background, no area fills except water, black labels with wide white halos.
  contrast: {
    background: '#ffffff',
    hide: (source, layer) => layer.type === 'fill' && !WATER.test(source),
    recolor: (c, key, layer) => {
      if (onIcon(layer)) return c;
      if (isText(key)) return rgb(0, 0, 0, c.a);
      if (isHalo(key)) return rgb(255, 255, 255, c.a);
      if (layer.type === 'fill') return grey(205, c.a);
      return grey(luma(c) * 0.45, c.a);
    },
    adjust: (layer) => {
      if (layer.type === 'symbol' && layer.paint?.['text-color'] !== undefined)
        layer.paint['text-halo-width'] = 2;
    },
  },
  // Streets, water, parks and place names only, in very light greys.
  minimal: {
    hide: (source) =>
      OTHER_PUBLIC_LANDS.test(source) ||
      TRAILS.test(source) ||
      /^(OpenStreetMap Building Footprints|Rail Lines|Municipal Boundaries(\/label)?|NHD Flowlines\/label)$/.test(
        source,
      ) ||
      source === 'Colorado City Point Locations',
    recolor: (c, key, layer) => (onIcon(layer) ? c : muted(c, key, 0.5)),
  },
  // Muted, except trails, parks and water, which keep colour; trails are drawn wider and greener.
  walking: {
    recolor: (c, key, layer) => {
      if (onIcon(layer)) return c;
      const source = String(layer['source-layer']);
      if (TRAILS.test(source)) return isText(key) ? rgb(20, 90, 45, c.a) : rgb(27, 127, 59, c.a);
      if (PARKS.test(source)) return c;
      if (WATER.test(source)) return isText(key) ? c : mix(c, WHITE, 0.35);
      if (source === 'Rail Lines') return grey(luma(c) * 0.8, c.a);
      return muted(c, key, 0.4);
    },
    adjust: (layer, source) => {
      if (source === 'COTREX' && layer.type === 'line' && layer.paint) {
        layer.paint['line-width'] = scaleWidth(layer.paint['line-width'] ?? 1, 1.8);
        delete layer.paint['line-dasharray'];
      }
    },
  },
  // The muted greys shifted towards a pale blue drawn from the CDOT dark blue.
  tinted: {
    background: '#eef1f6',
    recolor: (c, key, layer) => {
      if (onIcon(layer)) return c;
      const v = muted(c, key, 0.35).r / 255;
      const dark = isText(key) ? rgb(10, 22, 70, c.a) : rgb(40, 58, 110, c.a);
      return mix(dark, WHITE, v);
    },
  },
};

/** Rewrites a loaded state basemap style into one of the alternative looks. */
export function styleVariant(style: BasemapStyle, variant: BasemapVariant): BasemapStyle {
  const rules = RULES[variant];
  const layers: LayerSpecification[] = [];
  for (const original of style.layers as unknown as Layer[]) {
    const source = String(original['source-layer'] ?? '');
    if (rules.hide?.(source, original)) continue;
    const layer = structuredClone(original);
    if (layer.paint)
      for (const [key, value] of Object.entries(layer.paint))
        if (key.endsWith('-color'))
          layer.paint[key] = recolorValue(value, (c) => rules.recolor(c, key, layer));
    rules.adjust?.(layer, source);
    layers.push(layer as unknown as LayerSpecification);
  }
  if (rules.background)
    layers.unshift({
      id: `${BASEMAP_LAYER_PREFIX}background`,
      type: 'background',
      paint: { 'background-color': rules.background },
    });
  return { ...style, layers };
}
