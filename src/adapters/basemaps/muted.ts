import type { BasemapStyle, LayerSpecification } from './basemap';

/**
 * Share of the remaining distance to white added to every non-text colour. 0 keeps plain
 * greyscale; 1 would turn everything white.
 */
export const MUTED_LIGHTEN = 0.35;

export interface Rgba {
  r: number;
  g: number;
  b: number;
  a: number;
}

const HEX = /^#([0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$/i;
const RGB = /^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)$/i;

/** Parses the colour forms the state style uses: #rgb, #rgba, #rrggbb, #rrggbbaa, rgb() and rgba(). */
export function parseColor(value: string): Rgba | null {
  const hex = HEX.exec(value.trim());
  if (hex) {
    let digits = hex[1] as string;
    if (digits.length <= 4) digits = [...digits].map((d) => d + d).join('');
    const n = (i: number) => Number.parseInt(digits.slice(i, i + 2), 16);
    return { r: n(0), g: n(2), b: n(4), a: digits.length === 8 ? n(6) / 255 : 1 };
  }
  const rgb = RGB.exec(value.trim());
  if (rgb) {
    const [r, g, b] = [rgb[1], rgb[2], rgb[3]].map(Number) as [number, number, number];
    const a = rgb[4] === undefined ? 1 : Number(rgb[4]);
    if ([r, g, b].every((c) => c <= 255) && a <= 1) return { r, g, b, a };
  }
  return null;
}

/**
 * Converts a colour to grey by perceived brightness (Rec. 709 luma), then moves it `lighten` of
 * the way towards white. Transparency is kept.
 */
export function muteColor(value: string, lighten: number): string | null {
  const color = parseColor(value);
  if (!color) return null;
  const luma = 0.2126 * color.r + 0.7152 * color.g + 0.0722 * color.b;
  const grey = Math.round(luma + (255 - luma) * lighten);
  return color.a === 1
    ? `rgb(${grey}, ${grey}, ${grey})`
    : `rgba(${grey}, ${grey}, ${grey}, ${color.a})`;
}

/** Replaces every colour string inside a paint value, including inside expressions and stops. */
function muteValue(value: unknown, lighten: number): unknown {
  if (typeof value === 'string') return muteColor(value, lighten) ?? value;
  if (Array.isArray(value)) return value.map((item) => muteValue(item, lighten));
  if (typeof value === 'object' && value !== null)
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, muteValue(item, lighten)]),
    );
  return value;
}

/**
 * A greyscale, lightened version of a vector basemap, so coloured overlays stand out. Label text
 * stays plain greyscale (not lightened) to keep its contrast; halos and everything else are
 * lightened. Sprite images such as highway shields and fill patterns are pictures, not colours,
 * and keep their colours.
 */
export function muteBasemapStyle(style: BasemapStyle, lighten = MUTED_LIGHTEN): BasemapStyle {
  const layers = style.layers.map((layer) => {
    const paint = (layer as { paint?: Record<string, unknown> }).paint;
    if (!paint) return layer;
    const muted = Object.fromEntries(
      Object.entries(paint).map(([key, value]) => {
        if (!key.endsWith('-color')) return [key, value];
        return [key, muteValue(value, key === 'text-color' ? 0 : lighten)];
      }),
    );
    return { ...layer, paint: muted } as LayerSpecification;
  });
  return { ...style, layers };
}
